# WiFi Share

Send any file between two devices on the same Wi-Fi. No accounts, no cloud, no dependencies, just Python 3.8+.

## How it works
Run it on one device. It prints a URL. Open that URL on the other device (a phone browser works too) and drop files in. Files appear in the `received` folder and also show up in the page, so the other device can download them. Run it on both devices to send in both directions.

## Download (Windows)
Grab `WiFiShare.exe` from the [Releases](../../releases) page (built automatically by GitHub Actions) and double-click it. A small window shows a link; open it on your other device. Windows will ask about the firewall the first time: click Allow on private networks.

## Releasing a new version
Push to `main` and download the exe from the Actions run's artifacts, or tag a release:
```
git tag v1.0.0
git push origin v1.0.0
```
GitHub builds the exe and attaches it to the release.

## Usage from Python
```
python wifishare.py                      # open the app window
python wifishare.py serve                # terminal mode
python wifishare.py --port 9000          # custom port
python wifishare.py --dir ~/Downloads    # where received files go
python wifishare.py send photo.jpg http://192.168.1.20:8000/?key=abc123   # CLI send
```

## Notes
- Each run generates a random access key that is part of the URL. Use `--no-key` to turn it off.
- Only use on networks you trust. Traffic is plain HTTP, not encrypted.
- If the other device can't connect, allow Python through your firewall (Windows prompts the first time) and make sure both devices are on the same network, not a guest network with client isolation.
- Large files stream to disk, so file size isn't limited by RAM.

## License
MIT
