"""Regenerate explicit ORM columns from the authoritative Java entity definitions."""
import re
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT.parent / "bemodel-server/src/main/java/com/bemodel"
DEST = ROOT / "src/bemodel"


def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def main():
    packages = defaultdict(list)
    types = {"Long": "BigInteger().with_variant(Integer, 'sqlite')", "Integer": "Integer",
             "String": "Text", "LocalDateTime": "DateTime", "BigDecimal": "Numeric(20, 6)",
             "Double": "Float", "Boolean": "Boolean"}
    for path in sorted(JAVA.rglob("*.java")):
        source = path.read_text(encoding="utf-8")
        table = re.search(r'@TableName\("([^"]+)"\)', source)
        if not table:
            continue
        package = path.relative_to(JAVA).parts[0]
        fields = re.findall(r"private (\w+) (\w+);", source)
        code = [f"class {path.stem}(Base):", f"    __tablename__ = {table[1]!r}"]
        for kind, name in fields:
            typ = types[kind]
            args = ", primary_key=True, autoincrement=True" if name == "id" else ", nullable=True, server_default=FetchedValue()"
            code.append(f"    {snake(name)} = Column({snake(name)!r}, {typ}{args})")
        packages[package].append("\n".join(code))
    for package, classes in packages.items():
        directory = DEST / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").touch()
        header = ("# Generated from Java @TableName entities; regenerate with scripts/generate_models.py.\n"
                  "from sqlalchemy import Column, Integer, BigInteger, Text, DateTime, Numeric, Float, Boolean, FetchedValue\n"
                  "from bemodel.core.database import Base\n\n\n")
        (directory / "entities.py").write_text(header + "\n\n\n".join(classes) + "\n", encoding="utf-8")
    resources = ROOT.parent / "bemodel-server/src/main/resources"
    for sub, target in [("db/migration", "db/migration"), ("shacl", "resources/shacl")]:
        shutil.copytree(resources / sub, DEST / target, dirs_exist_ok=True)


if __name__ == "__main__":
    main()
