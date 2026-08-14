import { UpcomingScreen } from "@/components/layout/upcoming-screen";

export const metadata = { title: "Notebook" };

export default function NotebookPage() {
  return (
    <UpcomingScreen
      title="Notebook"
      description="Where your own thinking lives, linked to the sources behind it."
      milestone="Milestone 5"
      capabilities={[
        "Write in Markdown with LaTeX, tables, images, and code",
        "Link a note to the paper, project, hypothesis, or experiment it concerns",
        "Pull a saved passage straight into a note with its citation intact",
        "Ask Atlas which claims in your notes are not yet supported",
      ]}
    />
  );
}
