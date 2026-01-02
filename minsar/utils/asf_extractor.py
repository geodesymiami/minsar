import sys
import requests
from urllib.parse import urlparse, parse_qs

path=54
frame=97

def extract_coordinates(polygon_str):
    # Remove "POLYGON((" and "))" to isolate the coordinates
    coordinates = polygon_str.replace("POLYGON((", "").replace("))", "")

    # Split the coordinates into a list of (lon, lat) pairs
    points = [tuple(map(float, coord.split())) for coord in coordinates.split(",")]

    # Extract all longitudes and latitudes
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]

    # Compute the bounding box
    min_lon = min(longitudes)
    max_lon = max(longitudes)
    min_lat = min(latitudes)
    max_lat = max(latitudes)

    return min_lon, max_lon, min_lat, max_lat


def main(url):
    # Parse the URL
    parsed_url = urlparse(url)

    # Extract the fragment (part after #)
    fragment = parsed_url.fragment

    # Parse the query parameters from the fragment
    query_params = parse_qs(fragment.split('?')[1])

    min_lon, max_lon, min_lat, max_lat = extract_coordinates(query_params['polygon'][0])

    satellite = 'SENTINEL-1' if 'S1' in query_params['granule'][0] else None

    # Format the result
    bounding_box = f"{min_lon},{min_lat},{max_lon},{max_lat}"

    api = f"https://api-prod-private.asf.alaska.edu/services/search/param?bbox={bounding_box}&dataset={satellite}&processinglevel={query_params['productTypes'][0]}&flightDirection={query_params['flightDirs'][0]}&maxResults=250&output=jsonlite2"

    request = requests.get(api)
    if request.status_code == 200:
        print("Request was successful\n")
        data = request.json()

    for result in data.get("results", []):
        if result["gn"] not in query_params['granule'][0]:
            continue

        print(result['gn'])
        result_min_lon, result_max_lon, result_min_lat, result_max_lat = extract_coordinates(result["w"])

        # Check if the result polygon's bounding box contains the input polygon's bounding box
        if not (result_min_lon <= min_lon and result_max_lon >= max_lon and
            result_min_lat <= min_lat and result_max_lat >= max_lat):
            msg = f"Result {result['gn']} does not contain the input polygon"
            continue

        path = result["p"]
        msg = None

    if msg:
        raise ValueError(msg)

    return str(path), satellite, query_params['flightDirs'][0][0], min_lat, max_lat, min_lon, max_lon


if __name__ == '__main__':
    main(iargs=sys.argv)