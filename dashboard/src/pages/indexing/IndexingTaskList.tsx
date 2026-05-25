import { useI18n } from "../../i18n/context";
import type { IndexTask } from "../../api/types";
import { statusBadge } from "./indexingUtils";

interface Props {
  tasks: IndexTask[];
  activeTaskId: string | null;
  onViewDetails: (taskId: string) => void;
}

export function IndexingTaskList({ tasks, activeTaskId, onViewDetails }: Props) {
  const { t } = useI18n();
  const visibleTasks = tasks.filter((task) => task.task_id !== activeTaskId).slice(0, 10);

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">
        {t.indexing.recentTasks}
      </h3>
      {visibleTasks.length > 0 ? (
        <div className="space-y-2">
          {visibleTasks.map((task) => (
            <div
              key={task.task_id}
              className="flex items-center justify-between rounded-lg border border-gray-100 bg-white px-4 py-3 text-sm dark:border-gray-700 dark:bg-gray-900"
            >
              <div className="flex items-center gap-3">
                {statusBadge(task.status, t.indexing)}
                <span className="text-gray-700 dark:text-gray-200">
                  {task.mode} • {task.directory}
                </span>
                {task.repository && (
                  <span className="text-gray-400 dark:text-gray-500">({task.repository})</span>
                )}
              </div>
              <div className="flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
                <span>{new Date(task.created_at).toLocaleString()}</span>
                <button
                  type="button"
                  onClick={() => onViewDetails(task.task_id)}
                  className="text-sky-500 hover:text-sky-600 dark:text-sky-400 dark:hover:text-sky-300"
                >
                  {t.indexing.viewDetails}
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400 dark:text-gray-500">{t.indexing.noTasks}</p>
      )}
    </div>
  );
}
