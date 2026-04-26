import { useState } from "react";
import { X } from "lucide-react";
import FocusTrap from "../FocusTrap";

export interface GitPushConfig {
  remote_url: string;
  branch: string;
  commit_message_prefix: string;
}

interface GitPushConfigDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (config: GitPushConfig) => void;
}

export default function GitPushConfigDialog({ open, onClose, onConfirm }: GitPushConfigDialogProps) {
  const [remoteUrl, setRemoteUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [prefix, setPrefix] = useState("docs(wiki): ");

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 dark:bg-black/50">
      <FocusTrap onEscape={onClose}>
        <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-2xl dark:border-gray-700 dark:bg-gray-900">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Git Push Configuration</h3>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            >
              <X size={16} />
            </button>
          </div>
          <div className="mt-4 space-y-3">
            <label className="block">
              <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Remote URL</span>
              <input
                value={remoteUrl}
                onChange={(e) => setRemoteUrl(e.target.value)}
                placeholder="https://github.com/org/wiki-repo.git"
                className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Branch</span>
              <input
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-gray-600 dark:text-gray-400">Commit Message Prefix</span>
              <input
                value={prefix}
                onChange={(e) => setPrefix(e.target.value)}
                className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </label>
          </div>
          <div className="mt-5 flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                if (!remoteUrl.trim()) return;
                onConfirm({
                  remote_url: remoteUrl.trim(),
                  branch: branch.trim() || "main",
                  commit_message_prefix: prefix,
                });
                onClose();
              }}
              disabled={!remoteUrl.trim()}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
            >
              Confirm
            </button>
          </div>
        </div>
      </FocusTrap>
    </div>
  );
}
