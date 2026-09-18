"""Exercise the ORIGINAL compiled Java CryptoService against Python in both directions."""
import base64
import json
from pathlib import Path
import subprocess
from bemodel.core.crypto_service import CryptoService

root = Path(__file__).resolve().parents[2]
java = Path('D:/jdk/openjdk21.0.2/bin/java.exe')
slf4j = next((root / '.m2-test/org/slf4j/slf4j-api').rglob('slf4j-api-*.jar'))
classpath = str(root / 'bemodel-server/target/classes')+';'+str(slf4j)


def original(mode, secret, value):
    payload = '\n'.join(base64.b64encode(s.encode()).decode() for s in (secret, value))+'\n'
    process = subprocess.run([str(java), '--class-path', classpath, str(Path(__file__).with_name('JavaCryptoInterop.java')), mode], input=payload, text=True, capture_output=True, check=True)
    output = next(line[7:] for line in process.stdout.splitlines() if line.startswith('RESULT:'))
    return base64.b64decode(output).decode()


checks = []
for secret in ('', 'migration-synthetic-test-key', '中文密钥🔑'):
    crypto = CryptoService(secret)
    for plain in ('', 'mysql-test-password', '中文口令🔑\nline two'):
        encrypted_java = original('encrypt', secret, plain)
        assert crypto.decrypt(encrypted_java) == plain
        assert original('decrypt', secret, crypto.encrypt(plain)) == plain
        checks.append(dict(keyKind='default' if not secret else 'custom', plainBytes=len(plain.encode()), directions=2, passed=True))
destination = root / 'bemodel-server-py/artifacts/crypto-interop.json'
destination.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'{len(checks)*2} original Java/Python AES-GCM cross-decryption checks passed')
