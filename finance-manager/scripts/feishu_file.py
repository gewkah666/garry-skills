#!/Users/garry/.hermes/hermes-agent/venv/bin/python
"""feishu_file.py <path> [--caption TEXT] [--chat CHAT_ID]

Send a local file (the monthly report HTML, a CSV…) to the user's Feishu home channel as a file message.
Uses the gateway's own app credentials from ~/.hermes/.env (FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_HOME_CHANNEL).
Phantom's public report URL only opens inside the Phantom app; the file is what a Feishu user can open directly.
"""
import argparse
import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")))


def env(name: str) -> str:
    v = os.environ.get(name)
    if v:
        return v
    for line in (HOME / ".env").read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def send_file(path: str, caption: str = "", chat_id: str = "") -> dict:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (CreateFileRequest, CreateFileRequestBody, CreateMessageRequest,
                                     CreateMessageRequestBody)
    chat_id = chat_id or env("FEISHU_HOME_CHANNEL")
    if not chat_id:
        raise SystemExit("FEISHU_HOME_CHANNEL 未设置")
    builder = lark.Client.builder().app_id(env("FEISHU_APP_ID")).app_secret(env("FEISHU_APP_SECRET"))
    domain = env("FEISHU_DOMAIN")
    if domain and "lark" in domain:
        builder = builder.domain(lark.LARK_DOMAIN)
    client = builder.build()
    p = Path(path)
    with p.open("rb") as fh:
        req = CreateFileRequest.builder().request_body(
            CreateFileRequestBody.builder().file_type("stream").file_name(p.name).file(fh).build()).build()
        resp = client.im.v1.file.create(req)
    if not resp.success():
        raise SystemExit(f"upload failed: {resp.code} {resp.msg}")
    file_key = resp.data.file_key
    out = {"file_key": file_key}
    if caption:
        r = client.im.v1.message.create(CreateMessageRequest.builder().receive_id_type("chat_id").request_body(
            CreateMessageRequestBody.builder().receive_id(chat_id).msg_type("text").content(json.dumps({"text": caption})).build()).build())
        out["caption_ok"] = r.success()
    r = client.im.v1.message.create(CreateMessageRequest.builder().receive_id_type("chat_id").request_body(
        CreateMessageRequestBody.builder().receive_id(chat_id).msg_type("file").content(json.dumps({"file_key": file_key})).build()).build())
    if not r.success():
        raise SystemExit(f"send failed: {r.code} {r.msg}")
    out["message_id"] = r.data.message_id
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path"); ap.add_argument("--caption", default=""); ap.add_argument("--chat", default="")
    a = ap.parse_args()
    print(json.dumps(send_file(a.path, a.caption, a.chat), ensure_ascii=False))
