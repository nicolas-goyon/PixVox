# Image pixvox : Python + JDK 25 (compilation des mods), prête à l'emploi sans rien installer.
#   docker run --rm -v "$PWD:/work" ghcr.io/nicolas-goyon/pixvox export assets/*.py --pack out/pack --json
#   docker run --rm -v "$PWD:/work" ghcr.io/nicolas-goyon/pixvox mod assets/*.py --modid mon_mod --build
# Les sorties sont écrites dans le dossier monté (/work). Minecraft n'est jamais lancé.
FROM eclipse-temurin:25-jdk AS jdk

FROM python:3.15-slim
COPY --from=jdk /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk \
    PATH="/opt/java/openjdk/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# polices DejaVu : planches de revue identiques à celles de la CI Linux
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/pixvox
COPY pyproject.toml README.md ./
COPY pixvox ./pixvox
RUN pip install . && pixvox doctor

LABEL org.opencontainers.image.title="pixvox" \
      org.opencontainers.image.description="Atelier pixel-art / voxel-art Minecraft piloté par code (resource packs vérifiés, mods Fabric / NeoForge)" \
      org.opencontainers.image.source="https://github.com/nicolas-goyon/PixVox"

WORKDIR /work
ENTRYPOINT ["pixvox"]
CMD ["--help"]
