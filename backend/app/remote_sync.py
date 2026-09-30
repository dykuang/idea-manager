from __future__ import annotations

import hashlib
import errno
import os
import posixpath
import re
import stat
import threading
import time
import unicodedata
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import paramiko
except ImportError:  # Keep the local library usable if optional SSH packages aren't installed yet.
    class _ParamikoUnavailableError(Exception):
        pass

    class _ParamikoUnavailable:
        _ideaminer_missing = True
        SSHException = _ParamikoUnavailableError
        BadHostKeyException = _ParamikoUnavailableError

    paramiko = _ParamikoUnavailable()  # type: ignore[assignment]
from fastapi import APIRouter, HTTPException

from .database import DB_PATH, db
from .schemas import ProjectSyncExecute, ProjectSyncPreview, RemoteMachineCreate

router = APIRouter(prefix="/api/remotes", tags=["remote sync"])
SYNC_ROUTER = APIRouter(prefix="/api/project-sync", tags=["remote sync"])
_previews: dict[str, dict[str, Any]] = {}
_preview_lock = threading.Lock()
_PREVIEW_TTL = 15 * 60


def _machine(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in ("id", "name", "host", "username", "port", "root_path", "created_at", "updated_at")}


def _get_machine(machine_id: int) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT * FROM remote_machines WHERE id=?", (machine_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Remote machine not found")
    return _machine(row)


def _ssh_options(host_alias: str) -> dict[str, Any]:
    config_file = Path.home() / ".ssh" / "config"
    if not config_file.is_file():
        return {}
    config = paramiko.SSHConfig()
    try:
        with config_file.open(encoding="utf-8") as stream:
            config.parse(stream)
        return config.lookup(host_alias)
    except (OSError, paramiko.SSHException):
        return {}


def _open_sftp(machine: dict[str, Any]):
    if getattr(paramiko, "_ideaminer_missing", False):
        raise HTTPException(503, "SSH sync is unavailable until Paramiko is installed from backend/requirements.txt")
    options = _ssh_options(machine["host"])
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if known_hosts.is_file():
        client.load_host_keys(str(known_hosts))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    host = options.get("hostname", machine["host"])
    username = machine["username"] or options.get("user") or None
    port = machine["port"] or int(options.get("port", 22))
    identity_files = options.get("identityfile") or None
    if identity_files:
        identity_files = [os.path.expanduser(path) for path in identity_files]
    connect_options: dict[str, Any] = {
        "hostname": host,
        "port": port,
        "username": username,
        "key_filename": identity_files,
        "allow_agent": True,
        "look_for_keys": True,
        "timeout": 8,
        "banner_timeout": 8,
        "auth_timeout": 12,
    }
    proxy_command = options.get("proxycommand")
    if proxy_command:
        connect_options["sock"] = paramiko.ProxyCommand(proxy_command)
    try:
        client.connect(**connect_options)
        return client, client.open_sftp()
    except Exception:
        client.close()
        raise


def _close_sftp(client: Any, sftp: Any) -> None:
    try:
        try:
            sftp.close()
        except Exception:
            pass
    finally:
        try:
            client.close()
        except Exception:
            pass


def _is_missing(error: OSError) -> bool:
    return getattr(error, "errno", None) in (2, ENOENT) or "No such file" in str(error)


ENOENT = 2


def _clean_project_dir(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).strip()
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if cleaned in {"", ".", ".."}:
        raise HTTPException(400, "This project name cannot be used as a folder name")
    return cleaned[:120]


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(400, "Unsafe project-relative file path")
    normalized = path.as_posix()
    if "\x00" in normalized or "\\" in normalized:
        raise HTTPException(400, "Unsafe project-relative file path")
    return normalized


def _within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _local_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_hash(stream: Any) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _local_manifest(root_value: str, attachments: list[dict[str, Any]], allow_missing_root: bool) -> tuple[dict[str, dict[str, Any]], str]:
    root = Path(root_value).expanduser().resolve() if root_value else None
    if root and root.exists() and not root.is_dir():
        raise HTTPException(400, "The selected local project folder is not a directory")
    if root and not root.exists() and not allow_missing_root:
        raise HTTPException(400, "Choose an existing local project folder")
    manifest: dict[str, dict[str, Any]] = {}
    if root and root.is_dir():
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirnames[:] = [name for name in dirnames if not (current_path / name).is_symlink()]
            for filename in filenames:
                path = current_path / filename
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    resolved = path.resolve(strict=True)
                    if not _within(root, resolved):
                        continue
                    if resolved == DB_PATH.resolve() or resolved.name in {DB_PATH.name + "-wal", DB_PATH.name + "-shm"}:
                        continue
                    relative = _safe_relative(path.relative_to(root).as_posix())
                    manifest[relative] = {"size": resolved.stat().st_size, "sha256": _local_hash(resolved), "local_path": str(resolved)}
                except OSError:
                    continue
    for attachment in attachments:
        path = Path(attachment["absolute_path"]).expanduser()
        try:
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve(strict=True)
            if root and _within(root, resolved):
                continue
            digest = attachment["content_hash"] or _local_hash(resolved)
            filename = Path(attachment["display_name"]).name
            filename = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", filename).strip(" .") or "attachment"
            relative = _safe_relative(f"attachments/{digest[:12]}-{filename}")
            manifest[relative] = {"size": resolved.stat().st_size, "sha256": _local_hash(resolved), "local_path": str(resolved)}
        except OSError:
            continue
    return manifest, str(root) if root else ""


def _remote_base(sftp: Any, root_path: str) -> str:
    if not root_path or "\x00" in root_path or "\n" in root_path or "\r" in root_path:
        raise HTTPException(400, "Enter a valid remote root folder")
    if root_path == "~" or root_path.startswith("~/"):
        home = sftp.normalize(".")
        suffix = root_path[2:] if root_path.startswith("~/") else ""
        root_path = posixpath.join(home, suffix)
    if not posixpath.isabs(root_path):
        raise HTTPException(400, "Remote root folder must be absolute or start with ~/")
    return posixpath.normpath(root_path)


def _remote_project_path(sftp: Any, machine: dict[str, Any], project_name: str) -> str:
    base = _remote_base(sftp, machine["root_path"])
    folder = _clean_project_dir(project_name)
    target = posixpath.normpath(posixpath.join(base, folder))
    if target == base or not target.startswith(base.rstrip("/") + "/"):
        raise HTTPException(400, "Project folder is outside the configured remote root")
    return target


def _remote_manifest(sftp: Any, root: str) -> dict[str, dict[str, Any]]:
    try:
        root_attr = sftp.lstat(root)
    except OSError as error:
        if _is_missing(error):
            return {}
        raise
    if stat.S_ISLNK(root_attr.st_mode):
        raise HTTPException(400, "The remote project folder is a symbolic link")
    if not stat.S_ISDIR(root_attr.st_mode):
        raise HTTPException(400, "The remote project path is not a directory")
    manifest: dict[str, dict[str, Any]] = {}

    def visit(directory: str, relative_directory: str) -> None:
        for entry in sftp.listdir_attr(directory):
            relative = _safe_relative(posixpath.join(relative_directory, entry.filename))
            absolute = posixpath.join(directory, entry.filename)
            mode = entry.st_mode or 0
            if stat.S_ISLNK(mode):
                continue
            if stat.S_ISDIR(mode):
                visit(absolute, relative)
            elif stat.S_ISREG(mode):
                with sftp.open(absolute, "rb") as stream:
                    digest = _stream_hash(stream)
                manifest[relative] = {"size": int(entry.st_size or 0), "sha256": digest, "remote_path": absolute}

    visit(root, "")
    return manifest


def _project_data(project_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with db() as connection:
        project = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(404, "Project not found")
        if project["system_key"] == "recycle":
            raise HTTPException(400, "Recycle cannot be synced")
        rows = connection.execute(
            """SELECT DISTINCT a.*, p.workspace_path FROM attachments a
               JOIN projects p ON p.id=a.project_id
               JOIN ideas i ON i.project_id=p.id
               JOIN idea_attachments ia ON ia.attachment_id=a.id AND ia.idea_id=i.id
               WHERE p.id=? ORDER BY a.id""",
            (project_id,),
        ).fetchall()
    attachments = []
    for row in rows:
        if row["storage_mode"] == "managed":
            path = Path(row["path"])
            if path.as_posix().startswith("assets/"):
                path = DB_PATH.parent / path
            else:
                path = Path(row["workspace_path"]) / path
        else:
            path = Path(row["path"])
        attachments.append({"absolute_path": str(path), "display_name": row["display_name"], "content_hash": row["content_hash"]})
    return dict(project), attachments


def _expire_previews() -> None:
    now = time.monotonic()
    for key in [key for key, value in _previews.items() if value["expires"] < now]:
        _previews.pop(key, None)


def _comparison(source: dict[str, dict[str, Any]], destination: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(set(source) | set(destination), key=str.casefold):
        left = source.get(path)
        right = destination.get(path)
        if not right:
            status_name = "new"
        elif not left:
            status_name = "destination_only"
        elif left["sha256"] == right["sha256"]:
            status_name = "same"
        else:
            status_name = "conflict"
        rows.append({
            "path": path,
            "status": status_name,
            "source_size": left["size"] if left else None,
            "destination_size": right["size"] if right else None,
            "source_hash": left["sha256"] if left else None,
            "destination_hash": right["sha256"] if right else None,
        })
    return rows


@router.get("")
def list_machines() -> list[dict[str, Any]]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM remote_machines ORDER BY name COLLATE NOCASE").fetchall()
    return [_machine(row) for row in rows]


@router.post("")
def create_machine(payload: RemoteMachineCreate) -> dict[str, Any]:
    try:
        with db() as connection:
            cursor = connection.execute(
                "INSERT INTO remote_machines(name,host,username,port,root_path) VALUES(?,?,?,?,?)",
                (payload.name, payload.host, payload.username, payload.port, payload.root_path),
            )
            row = connection.execute("SELECT * FROM remote_machines WHERE id=?", (cursor.lastrowid,)).fetchone()
        return _machine(row)
    except Exception as error:
        if "UNIQUE" in str(error):
            raise HTTPException(409, "A remote machine with that name already exists") from error
        raise


@router.put("/{machine_id}")
def update_machine(machine_id: int, payload: RemoteMachineCreate) -> dict[str, Any]:
    try:
        with db() as connection:
            cursor = connection.execute(
                """UPDATE remote_machines SET name=?,host=?,username=?,port=?,root_path=?,
                   updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                (payload.name, payload.host, payload.username, payload.port, payload.root_path, machine_id),
            )
            if not cursor.rowcount:
                raise HTTPException(404, "Remote machine not found")
            row = connection.execute("SELECT * FROM remote_machines WHERE id=?", (machine_id,)).fetchone()
        return _machine(row)
    except HTTPException:
        raise
    except Exception as error:
        if "UNIQUE" in str(error):
            raise HTTPException(409, "A remote machine with that name already exists") from error
        raise


@router.delete("/{machine_id}")
def delete_machine(machine_id: int) -> dict[str, int]:
    with db() as connection:
        cursor = connection.execute("DELETE FROM remote_machines WHERE id=?", (machine_id,))
        if not cursor.rowcount:
            raise HTTPException(404, "Remote machine not found")
    return {"id": machine_id}


@router.post("/{machine_id}/check")
def check_machine(machine_id: int) -> dict[str, Any]:
    machine = _get_machine(machine_id)
    client = None
    sftp = None
    try:
        client, sftp = _open_sftp(machine)
        base = _remote_base(sftp, machine["root_path"])
        try:
            attr = sftp.lstat(base)
            root_exists = stat.S_ISDIR(attr.st_mode) and not stat.S_ISLNK(attr.st_mode)
            if not root_exists:
                return {"status": "connected", "root_exists": False, "message": "SSH is reachable, but the configured remote root is not a folder"}
        except OSError as error:
            if not _is_missing(error):
                raise
            root_exists = False
        return {"status": "connected", "root_exists": root_exists, "message": "SSH connection ready" if root_exists else "SSH is reachable; the remote root will be created on first sync"}
    except paramiko.BadHostKeyException as error:
        return {"status": "host_key_attention", "root_exists": False, "message": f"The SSH host key changed: {error}"}
    except paramiko.SSHException as error:
        message = str(error)
        status_name = "host_key_attention" if "known_hosts" in message.lower() or "host key" in message.lower() else "offline"
        return {"status": status_name, "root_exists": False, "message": message or "SSH connection failed"}
    except (OSError, TimeoutError) as error:
        return {"status": "offline", "root_exists": False, "message": str(error) or "Could not reach the SSH host"}
    finally:
        if client is not None and sftp is not None:
            _close_sftp(client, sftp)


@SYNC_ROUTER.post("/preview")
def preview_sync(payload: ProjectSyncPreview) -> dict[str, Any]:
    machine = _get_machine(payload.machine_id)
    project, attachments = _project_data(payload.project_id)
    local_value = payload.local_root.strip() or project["workspace_path"]
    if payload.direction == "pull" and not local_value:
        raise HTTPException(400, "Choose a local project folder before pulling files")
    source_local, resolved_local_root = _local_manifest(local_value, attachments, allow_missing_root=payload.direction == "pull")
    if payload.direction == "pull" and not Path(resolved_local_root).exists():
        raise HTTPException(400, "Choose an existing local project folder before pulling files")

    client = None
    sftp = None
    try:
        client, sftp = _open_sftp(machine)
        remote_project = _remote_project_path(sftp, machine, project["name"])
        remote_files = _remote_manifest(sftp, remote_project)
    except paramiko.BadHostKeyException as error:
        raise HTTPException(409, f"SSH host key needs attention: {error}") from error
    except paramiko.SSHException as error:
        raise HTTPException(503, f"SSH connection failed: {error}") from error
    except OSError as error:
        raise HTTPException(503, f"Could not inspect the remote project folder: {error}") from error
    finally:
        if client is not None and sftp is not None:
            _close_sftp(client, sftp)

    source, destination = (source_local, remote_files) if payload.direction == "push" else (remote_files, source_local)
    rows = _comparison(source, destination)
    preview_id = uuid.uuid4().hex
    with _preview_lock:
        _expire_previews()
        _previews[preview_id] = {
            "expires": time.monotonic() + _PREVIEW_TTL,
            "machine": machine,
            "project_name": project["name"],
            "direction": payload.direction,
            "local_root": resolved_local_root,
            "remote_project": remote_project,
            "source": source,
            "destination": destination,
            "items": {row["path"]: row for row in rows},
        }
    return {"preview_id": preview_id, "project_name": project["name"], "direction": payload.direction, "local_root": resolved_local_root, "remote_path": remote_project, "items": rows}


def _local_target(root: Path, relative: str) -> Path:
    relative = _safe_relative(relative)
    target = root.joinpath(*PurePosixPath(relative).parts)
    if not _within(root, target.resolve(strict=False)):
        raise HTTPException(400, "File path escapes the local project folder")
    cursor = root
    for part in PurePosixPath(relative).parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise HTTPException(400, "A symbolic link blocks the local destination path")
    if target.is_symlink():
        raise HTTPException(400, "The local destination file is a symbolic link")
    return target


def _remote_target(root: str, relative: str, sftp: Any) -> str:
    relative = _safe_relative(relative)
    target = posixpath.normpath(posixpath.join(root, *PurePosixPath(relative).parts))
    if not target.startswith(root.rstrip("/") + "/"):
        raise HTTPException(400, "File path escapes the remote project folder")
    cursor = root
    try:
        root_attr = sftp.lstat(root)
        if stat.S_ISLNK(root_attr.st_mode):
            raise HTTPException(400, "Remote project path cannot be a symbolic link")
    except OSError as error:
        if not _is_missing(error):
            raise
    for part in PurePosixPath(relative).parts:
        cursor = posixpath.join(cursor, part)
        try:
            attr = sftp.lstat(cursor)
        except OSError as error:
            if _is_missing(error):
                continue
            raise
        if stat.S_ISLNK(attr.st_mode):
            raise HTTPException(400, "A symbolic link blocks the remote destination path")
    return target


def _ensure_remote_directory(sftp: Any, directory: str) -> None:
    current = "/"
    for part in [piece for piece in directory.split("/") if piece]:
        current = posixpath.join(current, part)
        try:
            attr = sftp.lstat(current)
            if stat.S_ISLNK(attr.st_mode) or not stat.S_ISDIR(attr.st_mode):
                raise HTTPException(400, "Remote destination contains a non-directory path")
        except OSError as error:
            if not _is_missing(error):
                raise
            sftp.mkdir(current, 0o755)


def _atomic_upload(sftp: Any, source: dict[str, Any], destination: str) -> None:
    temp = f"{destination}.ideaminer-{uuid.uuid4().hex}.tmp"
    try:
        sftp.put(source["local_path"], temp)
        with sftp.open(temp, "rb") as stream:
            if _stream_hash(stream) != source["sha256"]:
                raise OSError("Uploaded file hash did not match the preview")
        try:
            sftp.posix_rename(temp, destination)
        except (AttributeError, NotImplementedError):
            try:
                sftp.remove(destination)
            except OSError as error:
                if not _is_missing(error):
                    raise
            sftp.rename(temp, destination)
        except OSError as error:
            unsupported = {errno.EINVAL, errno.ENOSYS, getattr(errno, "EOPNOTSUPP", errno.EINVAL), getattr(errno, "ENOTSUP", errno.EINVAL)}
            if error.errno not in unsupported:
                raise
            try:
                sftp.remove(destination)
            except OSError as remove_error:
                if not _is_missing(remove_error):
                    raise
            sftp.rename(temp, destination)
    except Exception:
        try:
            sftp.remove(temp)
        except OSError:
            pass
        raise


def _atomic_download(sftp: Any, source: dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(f".{destination.name}.ideaminer-{uuid.uuid4().hex}.tmp")
    try:
        sftp.get(source["remote_path"], str(temp))
        if _local_hash(temp) != source["sha256"]:
            raise OSError("Downloaded file hash did not match the preview")
        os.replace(temp, destination)
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@SYNC_ROUTER.post("/execute")
def execute_sync(payload: ProjectSyncExecute) -> dict[str, Any]:
    with _preview_lock:
        _expire_previews()
        preview = _previews.get(payload.preview_id)
    if not preview:
        raise HTTPException(410, "Sync preview expired; create a new preview")
    rows = preview["items"]
    selected_paths = list(dict.fromkeys(payload.selected_paths))
    delete_paths = list(dict.fromkeys(payload.delete_paths))
    if any(path not in rows or rows[path]["status"] not in {"new", "conflict"} for path in selected_paths):
        raise HTTPException(400, "Sync selection contains an invalid file path")
    if any(path not in rows or rows[path]["status"] != "destination_only" for path in delete_paths):
        raise HTTPException(400, "Deletion selection contains an invalid file path")

    machine = _get_machine(preview["machine"]["id"])
    client = None
    sftp = None
    transferred = 0
    deleted = 0
    try:
        client, sftp = _open_sftp(machine)
        remote_project = preview["remote_project"]
        if preview["direction"] == "push":
            _ensure_remote_directory(sftp, remote_project)
            current_destination = _remote_manifest(sftp, remote_project)
            source_manifest = preview["source"]
            for relative in selected_paths:
                source = source_manifest[relative]
                local_path = Path(source["local_path"])
                if local_path.is_symlink() or not local_path.is_file() or _local_hash(local_path) != source["sha256"]:
                    raise HTTPException(409, f"Source changed after preview: {relative}")
                previous = preview["destination"].get(relative)
                current = current_destination.get(relative)
                if current and current["sha256"] == source["sha256"]:
                    continue
                if (previous is None and current is not None) or (previous is not None and (current is None or current["sha256"] != previous["sha256"])):
                    raise HTTPException(409, f"Remote destination changed after preview: {relative}")
                target = _remote_target(remote_project, relative, sftp)
                _ensure_remote_directory(sftp, posixpath.dirname(target))
                _atomic_upload(sftp, source, target)
                transferred += 1
            for relative in delete_paths:
                previous = preview["destination"].get(relative)
                current = current_destination.get(relative)
                if current and previous and current["sha256"] == previous["sha256"]:
                    sftp.remove(current["remote_path"])
                    deleted += 1
                elif current:
                    raise HTTPException(409, f"Remote file changed after preview: {relative}")
        else:
            remote_manifest = _remote_manifest(sftp, remote_project)
            local_root = Path(preview["local_root"])
            local_root.mkdir(parents=True, exist_ok=True)
            source_manifest = preview["source"]
            for relative in selected_paths:
                source = source_manifest[relative]
                current_source = remote_manifest.get(relative)
                if not current_source or current_source["sha256"] != source["sha256"]:
                    raise HTTPException(409, f"Remote source changed after preview: {relative}")
                target = _local_target(local_root, relative)
                previous = preview["destination"].get(relative)
                if target.is_file() and _local_hash(target) == source["sha256"]:
                    continue
                if (previous is None and target.exists()) or (previous is not None and (not target.exists() or _local_hash(target) != previous["sha256"])):
                    raise HTTPException(409, f"Local destination changed after preview: {relative}")
                _atomic_download(sftp, source, target)
                transferred += 1
            for relative in delete_paths:
                previous = preview["destination"].get(relative)
                target = _local_target(local_root, relative)
                if target.is_file() and previous and _local_hash(target) == previous["sha256"]:
                    target.unlink()
                    deleted += 1
                elif target.exists():
                    raise HTTPException(409, f"Local file changed after preview: {relative}")
        with _preview_lock:
            _previews.pop(payload.preview_id, None)
        return {"transferred": transferred, "deleted": deleted, "skipped": len(selected_paths) - transferred, "project_name": preview["project_name"], "direction": preview["direction"]}
    except HTTPException:
        raise
    except (OSError, paramiko.SSHException) as error:
        raise HTTPException(502, f"Sync stopped after {transferred} files. Completed files are intact; preview again to continue. {error}") from error
    finally:
        if client is not None and sftp is not None:
            _close_sftp(client, sftp)
