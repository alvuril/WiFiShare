# WiFi Share

Send any file between two devices on the same Wi-Fi. No accounts, no cloud, no dependencies, just Python 3.8+.

## How it works
Run it on one device. It shows a QR code and a URL. Scan or open that on the other device (a phone browser works) and you can send files in both directions:

- **Other device -> this computer:** drop files on the page. They are saved on this computer (see "Where files are saved") and are not listed back on the other device.
- **This computer -> other device:** click **Send files...** in the app window (or send from the page if you opened it in a browser on this computer). The files are only offered to the other device. Nothing is copied into the received folder, and shared files are not kept after you close the app. Use the **To send** tab to stop sharing a file.

Run it on both devices to send in both directions app to app.

## Download (Windows)
1. Download `WiFiShare-windows.zip` from the [Releases](../../releases) page (built automatically by GitHub Actions).
2. Right-click it and choose **Extract All**. This creates one folder that holds everything: the app, its settings and your received files.
3. Open that folder and double-click `WiFiShare.exe`. Windows will ask about the firewall the first time: click Allow on private networks.

A window shows a QR code and a link. On your phone, point the camera at the QR code and tap the banner that appears (iPhone and Android both work), or type the link by hand. Received files are listed live in the window and saved in the `Received` folder inside the app's folder.

To update, extract the new version to a fresh folder and copy your `Received` folder across if you want to keep the files.

## Verify your download
Each release includes `WiFiShare-windows.zip.sha256`, a fingerprint of the zip. To check that your download is untouched, run this in PowerShell in the folder with the zip and compare the result to the text in that file:
```
Get-FileHash .\WiFiShare-windows.zip -Algorithm SHA256
```
If the two match (letter case doesn't matter), the file is the one GitHub built.

## Where files are saved
Files sent *to* this computer go to the `Received` folder inside the app's own folder, so nothing gets mixed into Downloads. Click **Change...** in the app window to pick another folder (it is remembered next time) or **Reset** to go back. Already-received files stay in the old folder. If the app's folder can't be written to (for example if it sits in Program Files), it falls back to `Downloads\WiFiShare Received`.

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
