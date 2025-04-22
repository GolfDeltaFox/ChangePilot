# Start from a Miniconda base image
FROM continuumio/miniconda3:latest

# Set working directory
WORKDIR /app

# Copy your environment YAML file
COPY changepilot.yml .

# Install mamba for faster package resolution
RUN conda install -y mamba -n base -c conda-forge

# Install build essentials before Conda steps
RUN apt-get update && apt-get install -y \
    g++ \
    cmake \
    make \
    git \
    && rm -rf /var/lib/apt/lists/*

ENV CC=/usr/bin/gcc
ENV CXX=/usr/bin/g++

# Create the environment
RUN mamba env create --yes -f changepilot.yml

# Activate by default
SHELL ["conda", "run", "-n", "changepilot", "/bin/bash", "-c"]

# Install gunicorn if needed (for prod Flask serving) or any extras
RUN conda run -n changepilot pip install gunicorn
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=development
# Copy app code into the image
COPY . .

# Expose Flask port
EXPOSE 8000

# Run the app
CMD ["conda", "run", "--no-capture-output", "-n", "changepilot", "python", "-u", "server.py"]
