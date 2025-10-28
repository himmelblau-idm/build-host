all:
	podman build -f Dockerfile.apt-ftparchive -t hbl/apt-ftparchive:bookworm .
