#!/bin/bash
set -e
set -x
exec > >(tee /var/log/user-data.log | logger -t user-data) 2>&1

echo "==== EC2 User Data Script START ===="

# 1. Create 2GB swap if not exists
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# 2. Base system deps
apt update && apt install -y wget git curl unzip software-properties-common \
    lsb-release gnupg libgl1 libglib2.0-0

# 3. GPU driver (only if needed)
if lspci | grep -i nvidia; then
  if ! command -v nvidia-smi &> /dev/null; then
    apt install -y ubuntu-drivers-common
    DRIVER=$(ubuntu-drivers list | grep nvidia | head -n1)
    [ -z "$DRIVER" ] && DRIVER="nvidia-driver-535"
    apt install -y "$DRIVER"
    reboot
  fi
fi

# 4. Install Miniconda to /opt
cd /opt
wget https://repo.anaconda.com/miniconda/Miniconda3-4.7.12.1-Linux-x86_64.sh -O miniconda.sh
bash miniconda.sh -b -p /opt/miniconda
export PATH="/opt/miniconda/bin:$PATH"

# 5. Create environment and install Python packages
/opt/miniconda/bin/conda create -y -n py38 python=3.8
/opt/miniconda/bin/conda run -n py38 pip install mtcnn==0.1.1 fawkes tqdm opencv-python boto3 awscli

# 6. Clone repo
cd /root
git clone -b colab_app https://github.com/JoeTSReynolds/CloakLib-Gen

# 7. Configure AWS CLI (replace with IAM or real credentials)
/opt/miniconda/envs/py38/bin/aws configure set aws_access_key_id [YOUR_AWS_ACCESS_KEY_ID]
/opt/miniconda/envs/py38/bin/aws configure set aws_secret_access_key [YOUR_AWS_SECRET_ACCESS_KEY]
/opt/miniconda/envs/py38/bin/aws configure set default.region eu-west-2

# 8. Run the script
cd /root/CloakLib-Gen
rm -rf frontend backend
nohup /opt/miniconda/bin/conda run -n py38 python dataset_generator.py --aws-spot --aws-bucket jointcloaking --aws-region eu-west-2 --all-levels > cloak.log 2>&1 &

echo "==== EC2 User Data Script COMPLETE ===="
