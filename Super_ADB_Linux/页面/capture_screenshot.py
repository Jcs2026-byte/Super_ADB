import sys
import time
from pathlib import Path

try:
    from PIL import ImageGrab
except ImportError:
    print('PIL not available')
    sys.exit(1)

time.sleep(4)
img = ImageGrab.grab()
img.save(str(Path(__file__).resolve().parents[2] / 'shot_about_open.png'))
print('saved')
