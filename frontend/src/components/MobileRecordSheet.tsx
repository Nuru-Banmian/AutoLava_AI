import type { RecordDetailPanelProps } from "@/components/RecordDetailPanel";
import { RecordDetailPanel } from "@/components/RecordDetailPanel";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

export interface MobileRecordSheetProps extends RecordDetailPanelProps {
  open: boolean;
  returnFocusTo: HTMLButtonElement | null;
  onOpenChange(open: boolean): void;
}

export function MobileRecordSheet({ open, record, canEdit, canDelete, onEdit, onDelete, returnFocusTo, onOpenChange }: MobileRecordSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        className="max-h-[90vh] overflow-y-auto rounded-t-2xl p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocusTo?.focus();
        }}
      >
        <SheetTitle className="sr-only">{record.date} 营业记录详情</SheetTitle>
        <RecordDetailPanel record={record} canEdit={canEdit} canDelete={canDelete} onEdit={onEdit} onDelete={onDelete} />
      </SheetContent>
    </Sheet>
  );
}
