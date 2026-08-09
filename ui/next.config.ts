import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output for the Docker image (infra/modules/container-apps-ui.bicep) -- traces only
  // the dependencies this app actually needs into .next/standalone instead of shipping the full
  // node_modules, same reasoning as the agent API's slim python:3.12-slim base image.
  output: "standalone",
};

export default nextConfig;
