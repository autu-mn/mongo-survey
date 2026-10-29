"""【第二阶段新增】不改数据库的 BSON 备份/验证工具。

在 backend 目录运行：
  .venv/Scripts/python -m scripts.backup_mongo --output ../backups/stage2-before.zip
  .venv/Scripts/python -m scripts.backup_mongo --verify ../backups/stage2-before.zip
备份包含当前数据库所有普通集合；BSON 保留 ObjectId、日期和数值类型。
"""

import argparse
import hashlib
import json
import struct
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from bson import BSON

from app.db import get_db


def backup_database(db, output: Path) -> dict:
    """只读数据库，创建一个不会覆盖既有文件的 ZIP/BSON 备份。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    collections = sorted(n for n in db.list_collection_names() if not n.startswith("system."))
    before = {name: db[name].count_documents({}) for name in collections}
    metadata = {
        "format": "mongo-bson-zip-v1",
        "database": db.name,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "collections": {},
    }
    with ZipFile(output, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for name in collections:
            digest = hashlib.sha256()
            count = 0
            with archive.open(f"{name}.bson", "w") as stream:
                for doc in db[name].find({}).sort("_id", 1):
                    blob = BSON.encode(doc)
                    stream.write(blob)
                    digest.update(blob)
                    count += 1
            metadata["collections"][name] = {"count": count, "sha256": digest.hexdigest()}
        archive.writestr("manifest.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    after = {name: db[name].count_documents({}) for name in collections}
    if before != after or any(before[name] != metadata["collections"][name]["count"]
                              for name in collections):
        raise RuntimeError("备份期间集合数量发生变化；请停止写入后重新备份")
    verify_backup(output)
    return metadata


def verify_backup(path: Path) -> dict:
    """读取 ZIP 内每份 BSON，核对文档边界、数量和 SHA-256。"""
    with ZipFile(path, "r") as archive:
        metadata = json.loads(archive.read("manifest.json"))
        if metadata.get("format") != "mongo-bson-zip-v1":
            raise ValueError("不支持的备份格式")
        expected_names = {f"{name}.bson" for name in metadata["collections"]} | {"manifest.json"}
        if set(archive.namelist()) != expected_names:
            raise ValueError("备份的集合文件与清单不一致")
        for name, expected in metadata["collections"].items():
            digest = hashlib.sha256()
            count = 0
            with archive.open(f"{name}.bson", "r") as stream:
                while length_bytes := stream.read(4):
                    if len(length_bytes) != 4:
                        raise ValueError(f"{name}: BSON 长度不完整")
                    length = struct.unpack("<i", length_bytes)[0]
                    if length < 5:
                        raise ValueError(f"{name}: BSON 长度无效")
                    blob = length_bytes + stream.read(length - 4)
                    if len(blob) != length:
                        raise ValueError(f"{name}: BSON 文档截断")
                    BSON(blob).decode()
                    digest.update(blob)
                    count += 1
            if count != expected["count"] or digest.hexdigest() != expected["sha256"]:
                raise ValueError(f"{name}: 数量或校验和不匹配")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="第二阶段 MongoDB BSON 备份/验证")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path, help="新备份路径；不会覆盖已有文件")
    action.add_argument("--verify", type=Path, help="只验证已有备份")
    args = parser.parse_args()
    metadata = verify_backup(args.verify) if args.verify else backup_database(get_db(), args.output)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
