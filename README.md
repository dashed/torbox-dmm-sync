# torbox-dmm-sync

> Sync DMM magnet links to TorBox.

Credits: https://gist.github.com/eliasbenb/10a4a49f3feb9df19b0b8ed838babb82

## Usage instructions

0. Export and download your DMM backup JSON from: https://debridmediamanager.com/library
1. Install `uv`. See: https://docs.astral.sh/uv/getting-started/installation/

2. Run the script using one of these methods:
   ```bash
   # Using environment variables
   TORBOX_API_KEY="your-api-key" DMM_BACKUP_JSON_FILE="path/to/dmm-backup.json" uv run torbox-magnet-importer.py

   # Using command line arguments
   uv run torbox-magnet-importer.py --api-key "your-api-key" --input-file "path/to/dmm-backup.json"

   # Dry run (simulate without making changes)
   uv run torbox-magnet-importer.py --api-key "your-api-key" --input-file "path/to/dmm-backup.json" --dry-run
   ```

### Options

- `--api-key`: TorBox API key (can also use TORBOX_API_KEY env var)
- `--input-file`: Path to DMM backup JSON file (can also use DMM_BACKUP_JSON_FILE env var)
- `--dry-run`: Perform a dry run without making any changes
- `--no-log-file`: Disable logging to file

Get torbox API key from: https://torbox.app/settings