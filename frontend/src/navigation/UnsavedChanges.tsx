import { createContext, type PropsWithChildren, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useBeforeUnload, useBlocker } from "react-router-dom";

import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";

interface PendingTransition {
  proceed(): void;
  cancel?(): void;
}

interface UnsavedChangesValue {
  dirty: boolean;
  markDirty(dirty: boolean): void;
  requestTransition(proceed: () => void, cancel?: () => void): void;
  resetUnsavedChanges(): void;
}

const UnsavedChangesContext = createContext<UnsavedChangesValue | null>(null);

function BeforeUnloadGuard() {
  useBeforeUnload(useCallback((event) => {
    event.preventDefault();
    event.returnValue = "";
  }, []));
  return null;
}

export function UnsavedChangesProvider({ children }: PropsWithChildren) {
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState<PendingTransition | null>(null);
  const pendingRef = useRef<PendingTransition | null>(null);
  const requestTransition = useCallback((proceed: () => void, cancel?: () => void) => {
    if (!dirty) {
      proceed();
      return;
    }
    if (pendingRef.current) {
      cancel?.();
      return;
    }
    const next = { proceed, cancel };
    pendingRef.current = next;
    setPending(next);
  }, [dirty]);
  const resetUnsavedChanges = useCallback(() => {
    const active = pendingRef.current;
    pendingRef.current = null;
    active?.cancel?.();
    setPending(null);
    setDirty(false);
  }, []);
  const cancel = () => {
    const active = pendingRef.current;
    pendingRef.current = null;
    active?.cancel?.();
    setPending(null);
  };
  const discard = () => {
    const proceed = pendingRef.current?.proceed;
    pendingRef.current = null;
    setPending(null);
    setDirty(false);
    proceed?.();
  };

  return <UnsavedChangesContext.Provider value={{ dirty, markDirty: setDirty, requestTransition, resetUnsavedChanges }}>
    {dirty && <BeforeUnloadGuard />}
    {children}
    <AlertDialog open={Boolean(pending)} onOpenChange={(open) => { if (!open) cancel(); }}>
      <AlertDialogContent>
        <AlertDialogHeader><AlertDialogTitle>放弃未保存的修改？</AlertDialogTitle><AlertDialogDescription>当前修改尚未保存。离开后，这些修改将丢失。</AlertDialogDescription></AlertDialogHeader>
        <AlertDialogFooter><AlertDialogCancel>继续编辑</AlertDialogCancel><AlertDialogAction onClick={discard}>放弃修改</AlertDialogAction></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </UnsavedChangesContext.Provider>;
}

export function useUnsavedChanges() {
  const value = useContext(UnsavedChangesContext);
  if (!value) throw new Error("useUnsavedChanges must be used within UnsavedChangesProvider");
  return value;
}

export function UnsavedRouteGuard() {
  const { dirty, requestTransition } = useUnsavedChanges();
  const blocker = useBlocker(dirty);
  const requested = useRef(false);
  useEffect(() => {
    if (blocker.state !== "blocked") {
      requested.current = false;
      return;
    }
    if (requested.current) return;
    requested.current = true;
    requestTransition(() => blocker.proceed(), () => blocker.reset());
  }, [blocker, requestTransition]);
  return null;
}
