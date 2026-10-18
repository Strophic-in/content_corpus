// A template (unlike the layout) is mounted afresh on every navigation, so each page
// — and the loading skeleton before it — gets the rise-in animation (globals.css).
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="page-in">{children}</div>;
}
