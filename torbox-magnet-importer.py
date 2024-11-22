import requests
import logging
from typing import List, Set
import time
from datetime import datetime
import os
import json
import argparse
from dataclasses import dataclass

@dataclass
class Magnet:
    hash: str
    filename: str | None = None

    def to_uri(self) -> str:
        """Generate a magnet URI from the hash and filename."""
        uri = f"magnet:?xt=urn:btih:{self.hash}"
        if self.filename:
            uri += f"&dn={self.filename}"
        return uri

def setup_logging(log_to_file: bool = True) -> None:
    """
    Configure the logging system with both console and file output.

    Args:
        log_to_file (bool): If True, logs will be written to a timestamped file in addition to console output.
                           If False, logs will only be written to console.

    The log file name format is: torbox_sync_YYYYMMDD_HHMMSS.log
    """
    handlers = [logging.StreamHandler()]
    if log_to_file:
        handlers.append(
            logging.FileHandler(
                f'torbox_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
            )
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )

class TorBoxManager:
    """
    Manages interactions with the TorBox API for torrent operations.

    This class handles retrieving existing torrents, loading magnet links from DMM backup files,
    and creating new torrents in TorBox.

    Attributes:
        api_key (str): The TorBox API authentication key
        base_url (str): The base URL for TorBox API endpoints
        headers (dict): HTTP headers including authentication and cache control
        dry_run (bool): If True, simulates operations without making actual API calls
    """

    def __init__(self, api_key: str, base_url: str = "https://api.torbox.app/v1", dry_run: bool = False):
        """
        Initialize the TorBox manager.

        Args:
            api_key (str): TorBox API key for authentication
            base_url (str): Base URL for the TorBox API
            dry_run (bool): If True, simulates operations without making actual changes
        """
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {api_key}", "bypass_cache": "true", "limit": "2147483647"}
        self.dry_run = dry_run

    def _make_request(self, method: str, endpoint: str, max_retries: int = 3, **kwargs) -> requests.Response:
        """
        Make an HTTP request to the TorBox API with retry logic and exponential backoff.

        This method wraps the requests library to provide:
        - Automatic retry on failure with exponential backoff
        - Consistent header injection
        - URL construction from base URL and endpoint
        - Error logging and handling

        Args:
            method (str): HTTP method to use (e.g., 'GET', 'POST')
            endpoint (str): API endpoint to call (e.g., 'api/torrents/mylist')
            max_retries (int, optional): Maximum number of retry attempts. Defaults to 3.
            **kwargs: Additional arguments to pass to requests.request()
                     Common kwargs include:
                     - params: dict of URL parameters
                     - data: dict of form data
                     - json: dict to send as JSON

        Returns:
            requests.Response: The successful response from the API

        Raises:
            requests.exceptions.RequestException: If all retry attempts fail

        Example:
            response = self._make_request('GET', 'api/torrents/mylist', params={'limit': 100})
        """
        # Add authorization and cache control headers to the request
        kwargs["headers"] = self.headers
        
        # Construct the full URL by combining base URL and endpoint
        url = f"{self.base_url}/{endpoint}"

        # Try the request up to max_retries times
        for attempt in range(max_retries):
            try:
                # Log the attempt and make the request
                logging.info(f"Requesting {url} with method {method} (attempt {attempt + 1}/{max_retries})")
                res = requests.request(method, url, **kwargs)
                
                # Raise an exception for bad status codes (4xx, 5xx)
                res.raise_for_status()
                
                # Add a small delay after successful request to prevent rate limiting
                time.sleep(5 * (attempt + 1))
                
                return res

            except requests.exceptions.RequestException as e:
                # Calculate wait time using exponential backoff: 5, 10, 20 seconds...
                wait_time = 5 * (2**attempt)
                logging.warning(f"Attempt {attempt + 1}/{max_retries} failed: {str(e)}")

                if attempt < max_retries - 1:
                    # If we have more retries left, wait and try again
                    logging.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    # If we're out of retries, log the error and re-raise the exception
                    logging.error(f"Max retries reached for {endpoint}")
                    raise

    def get_existing_torrents(self) -> Set[str]:
        """
        Retrieve all existing and queued torrents from TorBox.

        Returns:
            Set[str]: A set of lowercase torrent hashes that already exist in TorBox

        The method makes two API calls:
        1. Gets the list of existing torrents
        2. Gets the list of queued torrents
        
        A delay of 5 seconds is added between API calls to prevent rate limiting.
        """
        if self.dry_run:
            logging.info("[DRY RUN] Would fetch existing torrents")
            return set()

        existing_hashes = set()
        
        # First, get existing torrents
        try:
            response = self._make_request(
                "GET", "api/torrents/mylist", params={"bypass_cache": "true"}
            )
            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                for torrent in data.get("data", []):
                    if torrent.get("hash"):
                        existing_hashes.add(torrent["hash"].lower())
            else:
                logging.error(f"Failed to get existing torrents: {data.get('detail')}")
        except Exception as e:
            logging.error(f"Error getting existing torrents: {str(e)}")

        # Wait before making the second API call
        time.sleep(5)

        # Then, get queued torrents
        try:
            response = self._make_request("GET", "api/torrents/getqueued")
            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                for torrent in data.get("data", []):
                    if torrent.get("hash"):
                        existing_hashes.add(torrent["hash"].lower())
            else:
                logging.error(f"Failed to get queued torrents: {data.get('detail')}")
        except Exception as e:
            logging.error(f"Error getting queued torrents: {str(e)}")

        logging.info(f"Found {len(existing_hashes)} existing/queued torrents")
        return existing_hashes

    def load_magnet_links(self, filename: str) -> List[Magnet]:
        """
        Load and convert torrent information from a DMM backup JSON file into Magnet objects.

        Args:
            filename (str): Path to the DMM backup JSON file

        Returns:
            List[Magnet]: List of Magnet objects generated from the backup file
        """
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            magnets = []
            for item in data:
                if "hash" in item:
                    magnet = Magnet(
                        hash=item["hash"],
                        filename=item.get("filename")  # Use get() to handle missing filename
                    )
                    magnets.append(magnet)

            logging.info(f"Loaded {len(magnets)} magnet links from {filename}")
            return magnets
        except Exception as e:
            logging.error(f"Error loading magnet links from JSON file: {str(e)}")
            return []

    def create_torrent(self, magnet: Magnet) -> bool:
        """
        Create a new torrent in TorBox using a magnet link.

        Args:
            magnet (Magnet): The Magnet object to add

        Returns:
            bool: True if the torrent was added successfully, False otherwise
        """
        if self.dry_run:
            logging.info(f"[DRY RUN] Would add torrent: {magnet.hash}")
            return True

        try:
            response = self._make_request(
                "POST", "api/torrents/createtorrent", data={"magnet": magnet.to_uri()}
            )
            response.raise_for_status()
            data = response.json()

            if data.get("success"):
                logging.info(f"Successfully added torrent: {data.get('detail')}")
                return True
            else:
                logging.error(f"Failed to add torrent: {data.get('detail')}")
                return False
        except Exception as e:
            logging.error(f"Error creating torrent: {str(e)}")
            return False

    def process_magnets(self, magnets: List[Magnet], existing_hashes: Set[str]):
        """
        Process a list of Magnet objects and add them to TorBox if they don't already exist.

        Args:
            magnets (List[Magnet]): List of Magnet objects to process
            existing_hashes (Set[str]): Set of torrent hashes that already exist in TorBox

        Returns:
            int: Number of successfully added torrents
        """
        total = len(magnets)
        successful = 0

        for idx, magnet in enumerate(magnets, 1):
            torrent_hash = magnet.hash.lower()

            if torrent_hash in existing_hashes:
                logging.info(
                    f"Skipping existing torrent ({idx}/{total}): {torrent_hash}"
                )
                continue

            if self.create_torrent(magnet):
                successful += 1

            logging.info(f"Progress: {idx}/{total} processed ({successful} added)")

            # Add delay between API calls if not in dry-run mode
            if not self.dry_run:
                time.sleep(5)

        logging.info(
            f"Completed processing {total} magnets. Successfully added {successful} new torrents."
        )
        return successful

def parse_args():
    """
    Parse command line arguments for the script.

    Returns:
        argparse.Namespace: Parsed command line arguments

    Supported arguments:
    - --api-key: TorBox API key (can also use TORBOX_API_KEY env var)
    - --input-file: Path to DMM backup JSON file (can also use DMM_BACKUP_JSON_FILE env var)
    - --dry-run: Perform a dry run without making any changes
    - --no-log-file: Disable logging to file
    """
    parser = argparse.ArgumentParser(description="Sync DMM magnet links to TorBox")
    parser.add_argument(
        "--api-key",
        default=os.getenv("TORBOX_API_KEY"),
        help="TorBox API key (default: TORBOX_API_KEY env var)",
    )
    parser.add_argument(
        "--input-file",
        default=os.getenv("DMM_BACKUP_JSON_FILE", "dmm-backup.json"),
        help="DMM backup JSON file (default: DMM_BACKUP_JSON_FILE env var or dmm-backup.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run without making any changes",
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Disable logging to file",
    )
    return parser.parse_args()

def main():
    """
    Main entry point for the script.

    The function:
    1. Parses command line arguments
    2. Sets up logging
    3. Creates a TorBoxManager instance
    4. Gets existing torrents from TorBox
    5. Loads magnet links from the DMM backup file
    6. Processes the magnet links and adds new torrents to TorBox

    Returns:
        int: 0 for success, 1 for failure
    """
    args = parse_args()

    setup_logging(not args.no_log_file)

    if not args.api_key:
        logging.error("No API key provided. Use --api-key or set TORBOX_API_KEY environment variable")
        return 1
    
    if args.dry_run:
        logging.info("Running in dry-run mode - no changes will be made")

    torbox = TorBoxManager(args.api_key, dry_run=args.dry_run)

    existing_hashes = torbox.get_existing_torrents()

    magnets = torbox.load_magnet_links(args.input_file)
    if not magnets:
        logging.error("No magnet links loaded. Exiting.")
        return 1

    torbox.process_magnets(magnets, existing_hashes)
    return 0

if __name__ == "__main__":
    exit(main())