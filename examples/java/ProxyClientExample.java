// How the Java backend calls OpenAI through the proxy, using the official SDK.
//
// Maven:
//   <dependency>
//     <groupId>com.openai</groupId>
//     <artifactId>openai-java</artifactId>
//     <version>LATEST_VERSION</version>  <!-- check Maven Central -->
//   </dependency>
//
// Env vars:
//   LLM_PROXY_URL=http://<proxy-host>:4000
//   LLM_PROXY_KEY=sk-...   (the "java-backend" key, NOT the real OpenAI key)

import com.openai.client.OpenAIClient;
import com.openai.client.okhttp.OpenAIOkHttpClient;
import com.openai.errors.OpenAIServiceException;
import com.openai.models.chat.completions.ChatCompletion;
import com.openai.models.chat.completions.ChatCompletionCreateParams;

public class ProxyClientExample {

    private static final OpenAIClient CLIENT = OpenAIOkHttpClient.builder()
            .baseUrl(System.getenv().getOrDefault("LLM_PROXY_URL", "http://localhost:4000"))
            .apiKey(System.getenv("LLM_PROXY_KEY"))
            .build();

    public static String ask(String prompt) {
        ChatCompletionCreateParams params = ChatCompletionCreateParams.builder()
                .model("gpt-4o-mini")
                .addUserMessage(prompt)
                .maxCompletionTokens(300)   // cap output length = cap cost per call
                .build();
        try {
            ChatCompletion c = CLIENT.chat().completions().create(params);
            return c.choices().get(0).message().content().orElse("");
        } catch (OpenAIServiceException e) {
            String msg = String.valueOf(e.getMessage()).toLowerCase();
            if (msg.contains("budget")) {
                // Budget exhausted: show a friendly message instead of a 500.
                throw new IllegalStateException("LLM budget used up for this key/team.", e);
            }
            throw e;
        }
    }

    public static void main(String[] args) {
        System.out.println(ask("Say hello in five words."));
    }
}
