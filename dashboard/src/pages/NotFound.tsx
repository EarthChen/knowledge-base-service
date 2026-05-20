import { Link } from "react-router-dom";
import { useI18n } from "../i18n/context";

export default function NotFound() {
  const { t } = useI18n();
  return (
    <div className="flex flex-col items-center justify-center gap-4 p-12 text-center">
      <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">404</h1>
      <p className="text-sm text-gray-600 dark:text-gray-400">Page not found</p>
      <Link
        to="/"
        className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-700"
      >
        {t.nav.overview}
      </Link>
    </div>
  );
}
