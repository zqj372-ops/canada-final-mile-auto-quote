#!/usr/bin/env python3
"""Manage personal WeCom bots through the same authenticated API as the website."""
import argparse
import getpass
import json
import os
from pathlib import Path
import stat
import urllib.error
import urllib.parse
import urllib.request

class ClientError(Exception):
    pass


def protect_windows_file(path):
    """Give the file owner and SYSTEM access before writing any credential."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    set_security = advapi.SetFileSecurityW
    set_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    set_security.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    if not convert("D:P(A;;FA;;;OW)(A;;FA;;;SY)", 1, ctypes.byref(descriptor), None):
        raise ClientError("无法建立 Windows 私有凭证权限，已停止保存。")
    try:
        if not set_security(str(path), 0x80000004, descriptor):
            raise ClientError("无法设置 Windows 私有凭证权限，已停止保存。")
    finally:
        kernel.LocalFree(descriptor)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect must never send the binding code or credential to another URL.
        return None


def base_url(value):
    parsed = urllib.parse.urlsplit(value)
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (parsed.scheme not in {"https", "http"} or (parsed.scheme != "https" and not local)
            or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ClientError("服务地址必须为 HTTPS；仅本机测试允许 HTTP。")
    return value.rstrip("/")


def request(url, path, *, method="GET", data=None, credential=None):
    body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
    headers = {"Accept": "application/json", "User-Agent": "personal-wecom/1.0"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if credential:
        headers["Authorization"] = "Bearer " + credential
    req = urllib.request.Request(base_url(url) + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=90) as response:
            if response.status == 204:
                return None
            if "application/json" not in response.headers.get("Content-Type", ""):
                raise ClientError("服务没有返回 JSON，请检查服务地址和网关配置。")
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ClientError("登录无效或过期，请重新登录。") from None
        if exc.code == 403:
            raise ClientError("服务拒绝访问，请检查账号权限或联系管理员核对网关。") from None
        if exc.code == 404:
            raise ClientError("接口或本人机器人不存在，请检查服务是否已部署。") from None
        if 300 <= exc.code < 400:
            raise ClientError("服务返回重定向，已停止；请核实正确的 HTTPS 服务地址。") from None
        raise ClientError(f"服务请求失败（HTTP {exc.code}）；未自动重试。") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ClientError("连接失败或超时，结果尚未确认；未自动重试。若刚才提交了报价，请先查记录再决定是否重发。") from None
    except (ValueError, UnicodeError):
        raise ClientError("服务响应无法解析，结果尚未确认；未自动重试。") from None



def save_config(path, config):
    if path.exists() or path.is_symlink():
        raise ClientError("目标私有文件已存在，请使用新文件或先退出登录。")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # O_EXCL protects an existing binding from being overwritten by concurrent clients.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            protect_windows_file(path)
            json.dump(config, stream, ensure_ascii=False)
            stream.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


Error = ClientError


def read_session(path):
    if path.is_symlink() or (os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise Error("登录文件必须为私有普通文件（0600）。")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    base_url(value["base_url"])
    if not isinstance(value.get("credential"), str) or not value["credential"]:
        raise Error("登录文件无效，请重新登录。")
    return value


def execute(args):
    path = Path(args.session).expanduser()
    if args.command == "logout":
        if path.is_symlink():
            raise Error("登录文件不能是符号链接。")
        path.unlink(missing_ok=True)
        return {"local_session_removed": True, "server_token_revoked": False}
    if args.command == "login":
        if path.exists() or path.is_symlink():
            raise Error("已有登录文件，请先 logout，再重新登录。")
        password = Path(args.password_file).read_text(encoding="utf-8-sig").strip() if args.password_file else getpass.getpass("账号密码（不回显）：")
        url = base_url(args.base_url)
        result = request(url, "/auth/login", method="POST", data={"username": args.username, "password": password})
        save_config(path, {"base_url": url, "credential": result["access_token"]})
        return {"actor": result["actor"], "expires_in_seconds": result["expires_in_seconds"]}
    config = read_session(path)
    def bot_request(endpoint="", **options):
        return request(config["base_url"], "/wecom/my-bots" + endpoint, credential=config["credential"], **options)
    if args.command == "list":
        return bot_request()
    if args.command == "create":
        secret = Path(args.secret_file).read_text(encoding="utf-8-sig").strip() if args.secret_file else getpass.getpass("机器人 Secret（不回显）：")
        return bot_request(method="POST", data={"name": args.name, "bot_id": args.bot_id, "secret": secret})
    if args.command == "binding-code":
        # The command is a temporary credential: only write it to an exclusive private file.
        output = Path(args.output).expanduser()
        save_config(output, {})
        try:
            result = bot_request(f"/{args.id}/binding-code", method="POST", data={"revision": args.revision})
            with output.open("w", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False)
                stream.write("\n")
        except Exception:
            output.unlink(missing_ok=True)
            raise
        return {"bot": result["bot"], "binding_file": str(output), "expires_in_seconds": result["expires_in_seconds"]}
    changes = {"revision": args.revision}
    for field in ("name", "bot_id", "enabled"):
        if getattr(args, field, None) is not None:
            changes[field] = getattr(args, field)
    if args.secret_file:
        changes["secret"] = Path(args.secret_file).read_text(encoding="utf-8-sig").strip()
    elif args.prompt_secret:
        changes["secret"] = getpass.getpass("新的机器人 Secret（不回显）：")
    return bot_request(f"/{args.id}", method="PATCH", data=changes)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--session", default=str(Path.home() / ".config/personal-wecom/session.json"))
    commands = cli.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login")
    login.add_argument("--base-url", default="https://quote.freightclaw.net/api")
    login.add_argument("--username", required=True)
    login.add_argument("--password-file", help="Private UTF-8 file; otherwise prompt without echo")
    commands.add_parser("logout")
    commands.add_parser("list")
    create = commands.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--bot-id", required=True)
    create.add_argument("--secret-file", help="Private UTF-8 file; otherwise prompt without echo")
    edit = commands.add_parser("update")
    edit.add_argument("--id", required=True, type=int)
    edit.add_argument("--revision", required=True, type=int)
    edit.add_argument("--name")
    edit.add_argument("--bot-id")
    enabled = edit.add_mutually_exclusive_group()
    enabled.add_argument("--enable", dest="enabled", action="store_true")
    enabled.add_argument("--disable", dest="enabled", action="store_false")
    edit.set_defaults(enabled=None)
    secrets = edit.add_mutually_exclusive_group()
    secrets.add_argument("--secret-file")
    secrets.add_argument("--prompt-secret", action="store_true")
    bind = commands.add_parser("binding-code")
    bind.add_argument("--id", required=True, type=int)
    bind.add_argument("--revision", required=True, type=int)
    bind.add_argument("--output", required=True, help="New private file; will not overwrite")
    return cli


def main():
    try:
        result = execute(parser().parse_args())
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except (Error, OSError, ValueError, KeyError, EOFError) as exc:
        print(json.dumps({"ok": False, "error": str(exc) if isinstance(exc, Error) else "本地文件或响应格式无效，请检查后重试。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
