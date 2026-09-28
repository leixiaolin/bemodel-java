"""Compare original compiled Java JwtService and Python HMAC key-size checks."""
import json
import os
from pathlib import Path
import subprocess
import warnings
import jwt
from bemodel.auth.jwt_service import JwtService


def main():
    root = Path(__file__).resolve().parents[2]
    classpath = os.pathsep.join([str(root / "bemodel-server/target/classes"),
        *(str(p) for p in (root / ".m2-test").rglob("*.jar"))])
    rows, inputs = [], []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for length in (32, 48, 64):
            for algorithm in ("HS256", "HS384", "HS512"):
                secret = "k" * length
                token = jwt.encode({"sub": "test", "role": "VIEWER"}, secret, algorithm=algorithm)
                inputs.append(f"{length} {token}")
                rows.append(dict(keyBytes=length, algorithm=algorithm,
                    pythonAccepted=JwtService(secret).parse(token) is not None))
    java = str(Path(os.environ["JAVA_HOME"]) / "bin/java.exe") if os.name == "nt" else "java"
    result = subprocess.run([java, "-cp", classpath, str(Path(__file__).with_name("JavaJwtKeyCheck.java"))],
        input="\n".join(inputs) + "\n", text=True, capture_output=True, check=True)
    answers = [line.removeprefix("RESULT:") == "true" for line in result.stdout.splitlines() if line.startswith("RESULT:")]
    assert len(answers) == len(rows), result.stdout + result.stderr
    for row, accepted in zip(rows, answers):
        row["javaAccepted"] = accepted
    path = root / "bemodel-server-py/artifacts/jwt-key-parity.json"
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    assert all(row["javaAccepted"] == row["pythonAccepted"] for row in rows), rows
    print(f"{len(rows)} Java/Python JWT key checks passed")


if __name__ == "__main__":
    main()
