# FixPilot Sandbox Dockerfile - Java (Maven/Gradle)
# Provides isolated non-root test execution environment for Java projects

FROM maven:3.9-eclipse-temurin-21

# Create non-root user
RUN groupadd -r nonroot && useradd -r -g nonroot -m -d /home/nonroot nonroot

# Install Gradle
RUN apt-get update && apt-get install -y gradle && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /project

# Switch to non-root user
USER nonroot

# Default entrypoint - will use Maven or Gradle based on project
CMD ["mvn", "test"]