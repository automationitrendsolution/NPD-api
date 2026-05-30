import requests

SCRAPER_API_KEY = "fe5c1ce1538dd7b3c84acb2f3e45a882"

def fetch_amazon_search(keyword):
    amazon_url = f"https://www.amazon.com/s?k={keyword}"

    response = requests.get(
        "https://api.scraperapi.com",
        params={
            "api_key": SCRAPER_API_KEY,
            "url": amazon_url,
            "render": "true"
        },
        timeout=30
    )
    response.raise_for_status()
    return response.text

# from curl_cffi import requests


# def fetch_amazon_search(keyword, page=1):

#     url = f"https://www.amazon.com/s?k={keyword}&page={page}"

#     headers = {
#         "accept": "text/html,application/xhtml+xml",
#         "accept-language": "en-US,en;q=0.9",
#         "cache-control": "max-age=0",
#         "upgrade-insecure-requests": "1",
#     }

#     response = requests.get(
#         url,
#         headers=headers,
#         impersonate="chrome124"
#     )

#     return response.text