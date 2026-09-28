import com.bemodel.auth.JwtService;

class JavaJwtKeyCheck {
    public static void main(String[] args) throws Exception {
        var reader = new java.io.BufferedReader(new java.io.InputStreamReader(System.in));
        String line;
        while ((line = reader.readLine()) != null) {
            String[] parts = line.split(" ", 2);
            var service = new JwtService("k".repeat(Integer.parseInt(parts[0])));
            System.out.println("RESULT:" + service.parse(parts[1]).isPresent());
        }
    }
}
