# CloakLib-Gen
Generator for a library of cloaked and non cloaked images and videos

## Dependencies
Only works with python 3.8.x so make sure you are using 3.8 (e.g. 3.8.10). This is due to fawkes dependencies
Or use a virtual environment (recommended).

Libraries:
`pip install fawkes`
`pip install tqdm`

## Usage

`python image_lib_gen.py [-h] [--batch-size BATCH_SIZE] [--threads THREADS] [--mode {low,mid,high}] [--dir] input_media `

This will process images and videos given as input and add them to the (local) library in appropriate places. Does not delete the original input.
To process a folder use the `--dir` flag, and give the folder as the input.