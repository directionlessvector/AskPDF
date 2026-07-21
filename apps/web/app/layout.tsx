import "../styles/globals.css";

export const metadata = {
  title: "AskPDF AI",
  description: "Agentic RAG SaaS application",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
