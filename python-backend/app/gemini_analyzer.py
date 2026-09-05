import requests
import base64
import json
import os


class GeminiAnalyzer:
    def __init__(self):
        self.proxy_url = os.getenv("GEMINI_PROXY_URL", "http://localhost:8080")

    def analyze_image(self, image_bytes):
        # Convert image to base64
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        # Send to Gemini
        response = requests.post(
            f"{self.proxy_url}/analyze",
            json={"image": image_b64},
            timeout=5
        )

        if response.status_code == 200:
            return response.json()
        return None


# Test function
if __name__ == "__main__":
    with open("test.jpg", "rb") as f:
        analyzer = GeminiAnalyzer()
        result = analyzer.analyze_image(f.read())
        print(json.dumps(result, indent=2))
