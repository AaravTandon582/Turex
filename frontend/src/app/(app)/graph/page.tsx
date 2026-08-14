import { UpcomingScreen } from "@/components/layout/upcoming-screen";

export const metadata = { title: "Graph" };

export default function GraphPage() {
  return (
    <UpcomingScreen
      title="Knowledge graph"
      description="How your papers, authors, concepts, and questions actually connect."
      milestone="Milestone 6"
      capabilities={[
        "See the papers, concepts, and questions in a project as one connected picture",
        "Click any node to inspect what it links to and why",
        "Spot the concept two papers share that neither of them cites",
      ]}
    />
  );
}
