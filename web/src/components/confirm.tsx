import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Button, Modal } from "./ui";

type Ask = { title: string; body?: string; confirm?: string; danger?: boolean };
const Ctx = createContext<(a: Ask) => Promise<boolean>>(async () => false);

/** Yes/no dialog as a promise: `if (await confirm({...})) …` */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<(Ask & { resolve: (v: boolean) => void }) | null>(null);
  const ask = useCallback((a: Ask) => new Promise<boolean>((resolve) => setState({ ...a, resolve })), []);
  const done = (v: boolean) => {
    state?.resolve(v);
    setState(null);
  };
  return (
    <Ctx.Provider value={ask}>
      {children}
      <Modal open={!!state} onClose={() => done(false)} title={state?.title} width="max-w-sm">
        {state?.body && <p className="px-5 pt-4 text-[14px] text-muted">{state.body}</p>}
        <div className="flex justify-end gap-2 p-4">
          <Button variant="ghost" onClick={() => done(false)}>
            Cancel
          </Button>
          <Button variant={state?.danger ? "danger" : "primary"} onClick={() => done(true)} autoFocus>
            {state?.confirm ?? "OK"}
          </Button>
        </div>
      </Modal>
    </Ctx.Provider>
  );
}

export const useConfirm = () => useContext(Ctx);
