import Converter from "@/components/Converter";

const PRESERVED = [
  "Fonts",
  "Logos",
  "Images",
  "Tables",
  "Borders",
  "Colours",
  "Spacing",
  "Headers & footers",
  "Watermarks",
  "Signatures",
  "QR codes",
  "Barcodes",
  "Stamps",
];

const PRODUCTS = [
  { name: "Mkungi OCR", body: "Convert scanned documents into editable Word or Excel files." },
  { name: "Mkungi AI", body: "Identifies each document type and picks the best way to rebuild it." },
  { name: "Mkungi Templates", body: "Invoices, GRNs, payroll, reconciliations and more, ready to fill." },
  { name: "Mkungi Cloud", body: "Secure storage with searchable archives and version history." },
  { name: "Mkungi API", body: "Add OCR and document reconstruction to your own applications." },
];

const TEMPLATES = [
  "Invoices",
  "Quotations",
  "Receipts",
  "Delivery notes",
  "Goods received notes",
  "Purchase orders",
  "Payroll",
  "Asset registers",
  "Bank reconciliations",
  "Financial statements",
  "Inventory sheets",
  "Timesheets",
  "Petty cash vouchers",
];

const CUSTOMERS = [
  "NGOs",
  "Government ministries",
  "Banks",
  "Accounting firms",
  "Schools & universities",
  "Hospitals",
  "Retail",
  "Logistics",
  "Construction",
  "Law firms",
  "Auditors",
  "SMEs",
];

function Chips({ items }: { items: string[] }) {
  return (
    <ul className="flex flex-wrap gap-2">
      {items.map((i) => (
        <li key={i} className="rounded-full border border-ink/10 bg-white px-3 py-1 text-sm text-ink-soft">
          {i}
        </li>
      ))}
    </ul>
  );
}

export default function Home() {
  return (
    <main>
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5 sm:px-6">
        <span className="text-xl font-bold tracking-tight">
          Mkungi<span className="text-clay">.</span>
        </span>
        <nav className="flex gap-5 text-sm text-ink-soft">
          <a href="#products" className="hover:text-ink">Products</a>
          <a href="#templates" className="hover:text-ink">Templates</a>
          <a href={`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/docs`} className="hover:text-ink">
            API
          </a>
        </nav>
      </header>

      <section className="mx-auto grid max-w-6xl items-start gap-10 px-4 pb-16 pt-8 sm:px-6 lg:grid-cols-2 lg:pt-16">
        <div>
          <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-clay">AI document reconstruction</p>
          <h1 className="text-4xl font-bold leading-tight sm:text-5xl">From paper to perfectly editable.</h1>
          <p className="mt-5 max-w-xl text-lg text-ink-soft">
            Ordinary OCR gives you the words. Mkungi rebuilds the whole document — layout, tables, logos, stamps and
            signatures — as a Word or Excel file that looks like the original and is ready to edit.
          </p>
          <p className="mt-4 max-w-xl text-sm text-ink-soft">
            <em>Mkungi</em> is Chichewa for a bundle: everything on the page, gathered and put back together.
          </p>
        </div>
        <Converter />
      </section>

      <section className="border-y border-ink/10 bg-white">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
          <h2 className="text-2xl font-bold">Everything on the page comes back</h2>
          <p className="mb-6 mt-2 text-ink-soft">
            Signatures, stamps and codes are kept as images so they are never altered.
          </p>
          <Chips items={PRESERVED} />
        </div>
      </section>

      <section id="products" className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <h2 className="mb-6 text-2xl font-bold">Products</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {PRODUCTS.map((p) => (
            <div key={p.name} className="rounded-xl border border-ink/10 bg-white p-5">
              <h3 className="font-semibold">{p.name}</h3>
              <p className="mt-1 text-sm text-ink-soft">{p.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="templates" className="mx-auto grid max-w-6xl gap-10 px-4 pb-16 sm:px-6 lg:grid-cols-2">
        <div>
          <h2 className="mb-4 text-2xl font-bold">Templates</h2>
          <Chips items={TEMPLATES} />
        </div>
        <div>
          <h2 className="mb-4 text-2xl font-bold">Built for</h2>
          <Chips items={CUSTOMERS} />
        </div>
      </section>

      <footer className="border-t border-ink/10 py-8 text-center text-sm text-ink-soft">
        Mkungi — Africa&apos;s AI document digitisation platform.
      </footer>
    </main>
  );
}
