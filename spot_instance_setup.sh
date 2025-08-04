#!/bin/bash

# AWS Spot Instance Startup Script for Cloaking Processing
# This script sets up the environment and starts the cloaking process

set -e

# Configuration - modify these variables as needed
S3_BUCKET_NAME="${S3_BUCKET_NAME:-your-dataset-bucket}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLOAK_LEVEL="${CLOAK_LEVEL:-mid}"
BATCH_SIZE="${BATCH_SIZE:-10}"

# Logging
LOG_FILE="/var/log/spot-cloaking.log"
exec > >(tee -a $LOG_FILE)
exec 2>&1

echo "=========================================="
echo "Starting AWS Spot Instance Cloaking Setup"
echo "Time: $(date)"
echo "Instance ID: $(curl -s http://169.254.169.254/latest/meta-data/instance-id)"
echo "Instance Type: $(curl -s http://169.254.169.254/latest/meta-data/instance-type)"
echo "=========================================="

# Update system
echo "Updating system packages..."
apt-get update -y
apt-get upgrade -y

# Install dependencies
echo "Installing system dependencies..."
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    unzip \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgoogle-perftools4 \
    libtcmalloc-minimal4 \
    ffmpeg \
    libopencv-dev \
    python3-opencv

# Install NVIDIA drivers and CUDA if GPU instance
if lspci | grep -i nvidia > /dev/null; then
    echo "GPU detected, installing NVIDIA drivers and CUDA..."
    
    # Install NVIDIA drivers
    apt-get install -y ubuntu-drivers-common
    ubuntu-drivers autoinstall
    
    # Install CUDA toolkit
    wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/x86_64/cuda-keyring_1.0-1_all.deb
    dpkg -i cuda-keyring_1.0-1_all.deb
    apt-get update
    apt-get -y install cuda-toolkit-12-2
    
    # Add CUDA to PATH
    echo 'export PATH=/usr/local/cuda-12.2/bin${PATH:+:${PATH}}' >> /etc/environment
    echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.2/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}' >> /etc/environment
    source /etc/environment
fi

# Create working directory
WORK_DIR="/opt/cloaking"
mkdir -p $WORK_DIR
cd $WORK_DIR

# Set up Python environment with Miniconda
echo "Setting up Python environment with Miniconda..."

# Clean up any previous failed installs
rm -rf /opt/miniconda

# Download Miniconda installer (older version for compatibility)
wget https://repo.anaconda.com/miniconda/Miniconda3-4.7.12.1-Linux-x86_64.sh -O miniconda.sh

# Install Miniconda to /opt/miniconda
bash miniconda.sh -b -p /opt/miniconda

# Set up environment variables for conda
export PATH="/opt/miniconda/bin:$PATH"

# Verify conda is available
conda --version

# Create a Python 3.8 environment
conda create -y -n py38 python=3.8

# From this point forward, use the conda environment's pip directly
CONDA_ENV_PATH="/opt/miniconda/envs/py38"
PIP_CMD="$CONDA_ENV_PATH/bin/pip"
PYTHON_CMD="$CONDA_ENV_PATH/bin/python"

# Confirm Python version
$PYTHON_CMD --version

# Install Python dependencies using the environment's pip
echo "Installing Python dependencies..."
$PIP_CMD install --upgrade pip setuptools wheel

$PIP_CMD install boto3

# Install OpenCV and other image processing libraries
$PIP_CMD install opencv-python opencv-python-headless

# Install ML dependencies
$PIP_CMD install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
$PIP_CMD install tensorflow

# Install Fawkes
echo "Installing Fawkes..."
$PIP_CMD install fawkes

# Install other requirements if they exist
if [ -f "requirements.txt" ]; then
    $PIP_CMD install -r requirements.txt
fi

# Set up AWS credentials from instance role (assumed to be configured)
echo "Configuring AWS..."
aws configure set region $AWS_REGION

# Create systemd service for the cloaking process
echo "Creating systemd service..."
cat > /etc/systemd/system/spot-cloaking.service << EOF
[Unit]
Description=AWS Spot Instance Cloaking Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$WORK_DIR
Environment=PATH=/opt/miniconda/envs/py38/bin:/usr/local/cuda-12.2/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=LD_LIBRARY_PATH=/usr/local/cuda-12.2/lib64
Environment=S3_BUCKET_NAME=$S3_BUCKET_NAME
Environment=AWS_REGION=$AWS_REGION
ExecStart=/opt/miniconda/envs/py38/bin/python dataset_generator.py --aws-spot --aws-bucket $S3_BUCKET_NAME --aws-region $AWS_REGION --mode $CLOAK_LEVEL --batch-size $BATCH_SIZE
Restart=on-failure
RestartSec=30
StandardOutput=append:$LOG_FILE
StandardError=append:$LOG_FILE

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the service
echo "Starting cloaking service..."
systemctl daemon-reload
systemctl enable spot-cloaking.service
systemctl start spot-cloaking.service

# Create monitoring script
cat > /opt/cloaking/monitor.sh << 'EOF'
#!/bin/bash
while true; do
    echo "$(date): Service status:"
    systemctl status spot-cloaking.service --no-pager -l
    echo "=========================================="
    sleep 300  # Check every 5 minutes
done
EOF

chmod +x /opt/cloaking/monitor.sh

# Start monitoring in background
nohup /opt/cloaking/monitor.sh >> $LOG_FILE 2>&1 &

echo "=========================================="
echo "AWS Spot Instance setup completed!"
echo "Service status:"
systemctl status spot-cloaking.service --no-pager -l
echo "=========================================="
echo "To monitor the service:"
echo "  sudo journalctl -u spot-cloaking.service -f"
echo "To view logs:"
echo "  tail -f $LOG_FILE"
echo "To stop the service:"
echo "  sudo systemctl stop spot-cloaking.service"
echo "=========================================="
