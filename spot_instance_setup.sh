#cloud-config
cloud_final_modules:
  - [scripts-user, always]

#!/bin/bash
set -e
set -x
exec > >(tee /var/log/user-data.log | logger -t user-data) 2>&1

MARKER=/var/log/first-stage-complete

# Helper: check if NVIDIA driver is loaded and nvidia-smi works
nvidia_ready() {
    command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1
}

if [ ! -f "$MARKER" ]; then
  echo "==== FIRST BOOT: Setup ===="

  # 1. Swap
  if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi

  # 2. System deps
  apt update && apt install -y wget git curl unzip software-properties-common \
      lsb-release gnupg libgl1 libglib2.0-0 ubuntu-drivers-common

  # 3. Miniconda
  if [ ! -d /opt/miniconda ]; then
    cd /opt
    wget https://repo.anaconda.com/miniconda/Miniconda3-4.7.12.1-Linux-x86_64.sh -O miniconda.sh
    bash miniconda.sh -b -p /opt/miniconda
  fi
  export PATH="/opt/miniconda/bin:$PATH"

  # 4. Conda env + packages
  if ! /opt/miniconda/bin/conda env list | grep -q '^py38'; then
    /opt/miniconda/bin/conda create -y -n py38 python=3.8
    /opt/miniconda/bin/conda run -n py38 pip install mtcnn==0.1.1 fawkes tqdm opencv-python boto3 awscli torch
    /opt/miniconda/bin/conda run -n py38 pip install --upgrade typing_extensions
  fi

  # 5. Clone repo if missing
  if [ ! -d /root/CloakLib-Gen ]; then
    cd /root
    git clone https://github.com/JoeTSReynolds/CloakLib-Gen
  fi

  # 6. GPU driver
  if lspci | grep -qi nvidia && ! nvidia_ready; then
    DRIVER_RAW=$(ubuntu-drivers list | grep -i nvidia | head -n1 || true)
    DRIVER=$(echo "$DRIVER_RAW" | cut -d',' -f1 | awk '{print $1}')
    [ -z "$DRIVER" ] && DRIVER="nvidia-driver-535"
    apt install -y "$DRIVER"
    touch "$MARKER"
    echo "==== Driver installed, rebooting to load modules ===="
    reboot
    exit 0
  fi

  # If drivers already ready, skip reboot
  touch "$MARKER"
  echo "==== Drivers already working, continuing without reboot ===="
fi

# Second boot (or first boot if no reboot needed)
if [ -f "$MARKER" ]; then
  echo "==== STARTING SERVICE ===="
  export PATH="/opt/miniconda/bin:$PATH"
  cd /root/CloakLib-Gen
  rm -rf frontend backend
  /opt/miniconda/envs/py38/bin/aws configure set aws_access_key_id [YOUR_AWS_ACCESS_KEY_ID]
  /opt/miniconda/envs/py38/bin/aws configure set aws_secret_access_key [YOUR_AWS_SECRET_ACCESS_KEY]
  /opt/miniconda/envs/py38/bin/aws configure set default.region eu-west-2
  nohup /opt/miniconda/envs/py38/bin/python -u dataset_generator.py \
    --aws-spot --aws-bucket jointcloaking --aws-region eu-west-2 --all-levels \
    >> cloak.log 2>&1 &
fi
echo "==== Setup complete ===="