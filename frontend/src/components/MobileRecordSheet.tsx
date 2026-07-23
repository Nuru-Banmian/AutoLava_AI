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
        className="h-[calc(100dvh-1rem)] max-h-[calc(100dvh-1rem)] overflow-y-auto rounded-t-3xl p-4 pt-6 pb-[calc(1rem+env(safe-area-inset-bottom))] [&>button]:right-4 [&>button]:top-4 [&>button]:grid [&>button]:size-11 [&>button]:place-items-center [&>button_svg]:size-6"
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocusTo?.focus();
        }}
      >
        <SheetTitle className="sr-only">{record.date} 营业记录详情</SheetTitle>
        <RecordDetailPanel mobile record={record} canEdit={canEdit} canDelete={canDelete} onEdit={onEdit} onDelete={onDelete} />
      </SheetContent>
    </Sheet>
  );
}
