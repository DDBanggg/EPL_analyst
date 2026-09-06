from pathlib import Path
import requests

url = "https://www.football-data.co.uk/mmz4281/2627/E0.csv"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    )
}

response = requests.get(url, timeout=30)

response.raise_for_status()

# Take path
current_file = Path(__file__).resolve()
project_root = current_file.parents[2] 
raw_dir = project_root / "data" / "raw" / "football_data_uk"

raw_dir.mkdir(parents=True, exist_ok=True)

file_path = raw_dir / "E0_2026.csv"

with open(file_path, "wb") as file:
    file.write(response.content)

print(f"File downloaded and saved to {file_path}")

