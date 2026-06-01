FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive

# Python + curl (claude_code installs its own CLI at runtime via the adapter).
# tesseract-ocr is the OCR backend for the LLEM text_color dimension.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip curl ca-certificates tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

# Verifier deps: render (playwright) + the offline grader dims. numpy/pillow for
# colour + crops, scipy for LLEM block-matching, SSIM and Sobel edge maps (OCR via
# the tesseract binary above). No torch/litellm — perceptual (D6) and VLM (D8) are
# dropped, so grading is fully offline: no API key, no network at verify time.
RUN pip3 install --no-cache-dir --break-system-packages playwright numpy pillow scipy \
 && playwright install --with-deps chromium

# Fonts (F10/F11) — reference AND agent render in THIS image, so they share one font
# world (the reference is rendered in a container of this image at build time; see
# build_task.sh). A broad open palette (apt) + condensed/display/mono faces Google
# ships but apt doesn't, so designs render distinctively offline instead of collapsing
# to Liberation. fc-cache so Chromium sees them.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fontconfig fonts-liberation fonts-dejavu fonts-noto-core fonts-urw-base35 \
        fonts-ebgaramond fonts-cantarell fonts-firacode fonts-open-sans fonts-lato \
        fonts-roboto-unhinted \
 && mkdir -p /usr/share/fonts/truetype/extra && cd /usr/share/fonts/truetype/extra \
 && for u in \
      "ofl/robotocondensed/RobotoCondensed[wght].ttf" \
      "ofl/oswald/Oswald[wght].ttf" \
      "ofl/archivonarrow/ArchivoNarrow[wght].ttf" \
      "ofl/bebasneue/BebasNeue-Regular.ttf" \
      "ofl/jetbrainsmono/JetBrainsMono[wght].ttf" \
      "ofl/spacemono/SpaceMono-Regular.ttf" \
      "ofl/inter/Inter[opsz,wght].ttf" \
      "ofl/playfairdisplay/PlayfairDisplay[wght].ttf" \
      "ofl/sourceserif4/SourceSerif4[opsz,wght].ttf" \
    ; do curl -gfsSL -o "$(basename "$u")" "https://github.com/google/fonts/raw/main/$u" || true; done \
 && rm -rf /var/lib/apt/lists/*

# Resolve common proprietary family names (from generated CSS) → installed open faces,
# so designs render distinctively. NOTE: this aliases, it does not constrain the
# generator (kept free to pick any font; same-image rendering makes even an
# un-installed font fair — both sides fall back identically).
RUN printf '%s\n' \
 '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>' \
 '<alias><family>SF Mono</family><prefer><family>JetBrains Mono</family></prefer></alias>' \
 '<alias><family>Consolas</family><prefer><family>JetBrains Mono</family></prefer></alias>' \
 '<alias><family>Arial Narrow</family><prefer><family>Archivo Narrow</family></prefer></alias>' \
 '<alias><family>Helvetica Neue Condensed</family><prefer><family>Archivo Narrow</family></prefer></alias>' \
 '<alias><family>Palatino Linotype</family><prefer><family>P052</family></prefer></alias>' \
 '<alias><family>Hoefler Text</family><prefer><family>EB Garamond</family></prefer></alias>' \
 '<alias><family>Iowan Old Style</family><prefer><family>Source Serif 4</family></prefer></alias>' \
 '<alias><family>Big Caslon</family><prefer><family>Playfair Display</family></prefer></alias>' \
 '<alias><family>Segoe UI</family><prefer><family>Open Sans</family></prefer></alias>' \
 '<alias><family>Helvetica Neue</family><prefer><family>Inter</family></prefer></alias>' \
 '</fontconfig>' > /etc/fonts/conf.d/99-eval-aliases.conf \
 && fc-cache -f

# Grader + render code, importable as `pipeline.*`
COPY pipeline /opt/pipeline
ENV PYTHONPATH=/opt

# Agent input: the target screenshots, seeded into the workdir before the agent runs.
COPY target /app/target

WORKDIR /app
