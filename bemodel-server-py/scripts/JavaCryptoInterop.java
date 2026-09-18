import com.bemodel.common.CryptoService;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

class JavaCryptoInterop {
    public static void main(String[] args) throws Exception {
        var reader = new java.io.BufferedReader(new java.io.InputStreamReader(System.in, StandardCharsets.UTF_8));
        var decoder = Base64.getDecoder();
        String secret = new String(decoder.decode(reader.readLine()), StandardCharsets.UTF_8);
        String value = new String(decoder.decode(reader.readLine()), StandardCharsets.UTF_8);
        var crypto = new CryptoService(secret);
        String result = args[0].equals("encrypt") ? crypto.encrypt(value) : crypto.decrypt(value);
        System.out.println("RESULT:" + Base64.getEncoder().encodeToString(result.getBytes(StandardCharsets.UTF_8)));
    }
}
