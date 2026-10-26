import "./globals.css";

export const metadata = {
  title: "CFO Dashboard - Rentabilidad ABC & IFRS 18",
};

export default function RootLayout({ children }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
