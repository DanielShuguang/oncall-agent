import { useRef } from 'react';
import { RefreshCw, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { Visibility } from './access';

interface Props {
  uploading: boolean;
  reindexing: boolean;
  visibility: Visibility;
  rolesText: string;
  onUpload: (file: File) => void;
  onReindex: () => void;
  onChangeVisibility: (value: Visibility) => void;
  onChangeRolesText: (value: string) => void;
}

export function KbUploadCards({
  uploading,
  reindexing,
  visibility,
  rolesText,
  onUpload,
  onReindex,
  onChangeVisibility,
  onChangeRolesText,
}: Props) {
  const fileInput = useRef<HTMLInputElement>(null);

  return (
    <div className="grid gap-3 md:grid-cols-[1.4fr_1fr]">
      <Card className="gap-0 py-0">
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Upload className="size-4 text-brand" />
              上传知识文档
            </div>
            <p className="mt-1 mb-0 text-xs text-muted-foreground">
              支持 PDF / DOCX / MD / TXT；扫描 PDF 返回 PARSE_FAILED（v1 不做 OCR）。
              同一来源再次上传会覆盖旧文档。可见范围在点「选择文件」前生效。
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Select
                value={visibility}
                onValueChange={(value) => onChangeVisibility(value as Visibility)}
              >
                <SelectTrigger size="sm" className="text-xs" aria-label="文档可见范围">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="public">公开（所有登录用户）</SelectItem>
                  <SelectItem value="roles">指定角色</SelectItem>
                </SelectContent>
              </Select>
              {visibility === 'roles' && (
                <Input
                  value={rolesText}
                  aria-label="可见角色"
                  placeholder="hr,finance"
                  className="h-8 w-44 text-xs"
                  onChange={(event) => onChangeRolesText(event.target.value)}
                />
              )}
            </div>
          </div>
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.docx,.md,.markdown,.txt"
            className="hidden"
            aria-label="选择知识文档"
            onChange={(event) => {
              const file = event.target.files?.[0];
              // 先清空 value，才能连续两次选择同一个文件触发 change
              event.target.value = '';
              if (file) onUpload(file);
            }}
          />
          <Button
            size="sm"
            disabled={uploading || reindexing}
            onClick={() => fileInput.current?.click()}
          >
            {uploading ? '上传并索引中…' : '选择文件'}
          </Button>
        </CardContent>
      </Card>

      <Card className="gap-0 py-0">
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold">重建索引</div>
            <p className="mt-1 mb-0 text-xs text-muted-foreground">
              换 embedding 模型后重算全部向量，不重新切分源文件。
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={reindexing || uploading}
            onClick={onReindex}
          >
            <RefreshCw className={reindexing ? 'size-3.5 animate-spin' : 'size-3.5'} />
            {reindexing ? '重建中…' : '重建'}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
