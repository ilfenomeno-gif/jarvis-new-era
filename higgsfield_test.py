from dotenv import load_dotenv
import higgsfield_client

load_dotenv(".env.local")

print("Sending request to Higgsfield API...")

try:
    result = higgsfield_client.subscribe(
        "bytedance/seedance-2.5/text-to-video",
        arguments={
            "prompt": "A cinematic scene at sunset",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "output_format": "mp4",
            "generate_audio": True,
        },
    )
    print("Request successful! Video URL/Result:")
    print(result)
except Exception as e:
    print(f"An error occurred: {e}")
