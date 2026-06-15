all:
	podman build -f Dockerfile.apt-ftparchive -t hbl/apt-ftparchive:bookworm .
	podman build -f Dockerfile.dpkg-scanpackages -t hbl/dpkg-scanpackages:ubuntu26.04 .
