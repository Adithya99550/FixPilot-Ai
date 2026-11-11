# FixPilot Sandbox Dockerfile - Go
# Provides isolated non-root test execution environment for Go projects

FROM golang:1.22-alpine

# Create non-root user
RUN addgroup -S nonroot && adduser -S nonroot -G nonroot

# Create working directory
WORKDIR /project

# Switch to non-root user
USER nonroot

# Default entrypoint
CMD ["go", "test", "./..."]