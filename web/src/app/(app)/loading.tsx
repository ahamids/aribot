/**
 * Route-level loading UI for every /(app) page. Shows while the
 * Server Component fetches /status + /credentials + /positions etc.
 * over the network. Three skeleton cards are enough to give the
 * navigation a "something is happening" feel without committing to
 * a specific layout (different pages have different card stacks).
 */
export default function AppLoading() {
  return (
    <main className="flex-1 flex flex-col">
      <header className="px-4 py-4 sm:px-12 sm:py-6">
        <div className="h-8 w-24 rounded-md bg-paper outline-plum animate-pulse" />
      </header>

      <section className="flex-1 px-4 py-6 sm:px-12 sm:py-8">
        <div className="mx-auto w-full max-w-3xl flex flex-col gap-4 sm:gap-6">
          <SkeletonCard heightClass="h-24" />
          <SkeletonCard heightClass="h-40" />
          <SkeletonCard heightClass="h-32" />
        </div>
      </section>
    </main>
  );
}

function SkeletonCard({ heightClass }: { heightClass: string }) {
  return (
    <div
      className={`outline-plum rounded-[18px] bg-paper p-5 ${heightClass} animate-pulse`}
    >
      <div className="h-3 w-24 rounded-sm bg-cream-deep" />
      <div className="mt-3 h-6 w-3/4 rounded-md bg-cream-deep" />
      <div className="mt-2 h-4 w-1/2 rounded-md bg-cream-deep" />
    </div>
  );
}
