FROM python:3.11-slim

WORKDIR /app

# Base system deps:
#  - build-essential, libpq-dev: psycopg build
#  - curl: used by healthchecks / debugging
#  - libreoffice-{core,writer,impress,calc}: headless conversion of
#    .docx / .doc / .pptx / .ppt (and .xlsx if ever needed) to PDF
#  - fonts-*: wide font coverage so LibreOffice renders Office docs
#    with the intended layout. Carlito/Caladea are metric-compatible
#    with Calibri/Cambria (very common in Office files). Noto CJK
#    covers Chinese / Japanese / Korean. Dejavu, Liberation, URW
#    round out the Latin base.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    libreoffice-core \
    libreoffice-writer \
    libreoffice-impress \
    libreoffice-calc \
    fonts-liberation \
    fonts-liberation2 \
    fonts-dejavu \
    fonts-dejavu-core \
    fonts-dejavu-extra \
    fonts-noto \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    fonts-crosextra-carlito \
    fonts-crosextra-caladea \
    fonts-urw-base35 \
    fonts-opensymbol \
    fonts-linuxlibertine \
    fonts-sil-gentium \
    fonts-ipafont \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

# Microsoft core fonts (Arial, Times New Roman, Courier, Verdana, etc.)
# Lives in the Debian `contrib` repo and requires EULA acceptance via
# debconf. These are the real fonts Office docs reference by name, so
# installing them avoids any metric substitution drift.
RUN echo "deb http://deb.debian.org/debian bookworm main contrib" \
      > /etc/apt/sources.list.d/contrib.list \
    && apt-get update \
    && echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" \
      | debconf-set-selections \
    && apt-get install -y --no-install-recommends ttf-mscorefonts-installer \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app/backend

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
