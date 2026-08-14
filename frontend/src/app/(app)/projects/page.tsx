import { UpcomingScreen } from "@/components/layout/upcoming-screen";

export const metadata = { title: "Projects" };

export default function ProjectsPage() {
  return (
    <UpcomingScreen
      title="Projects"
      description="A research question, and everything you have gathered to answer it."
      milestone="Milestone 5"
      capabilities={[
        "State a research question and track what would answer it",
        "Record hypotheses with their supporting and contradicting evidence",
        "Plan experiments — variables, controls, metrics, and confounders",
        "Keep papers, notes, and conversations attached to the work they belong to",
      ]}
    />
  );
}
