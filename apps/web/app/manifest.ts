import type { MetadataRoute } from "next";

// Installable: "Add to Home Screen" opens the app full-screen on Discover, with no
// browser bar — the bottom tab bar is the navigation.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Content Corpus",
    short_name: "Corpus",
    description: "Discover ideas, plan and make Shorts.",
    start_url: "/discover",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#09090b",
    theme_color: "#09090b",
    icons: [
      { src: "/icons/192", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/512", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/512?maskable=1", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
