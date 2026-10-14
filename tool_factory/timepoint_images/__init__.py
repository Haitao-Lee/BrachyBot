"""Natural-language image operations through the real owned collection service."""
from tool_factory import BaseTool, ToolResult
from web.timepoints import TimepointError
from web.timepoint_messages import resolve_timepoint_language, timepoint_error
from web.workspace_store import WorkspaceError


class TimepointImagesTool(BaseTool):
    name = 'timepoint_images'
    description = (
        "List or manage uploaded images in the submission-captured Table Viewer. "
        "Use list to obtain actual stable image IDs and original filenames. "
        "Show/hide changes only the mutually exclusive image background, never "
        "the planning reference. Move only changes the preop/intraop/unclassified "
        "Data Tree grouping. Appearance changes marker color, opacity and window/level. "
        "Set_reference explicitly changes the planning source and invalidates "
        "incompatible downstream data; do not use it merely to view an image. "
        "Delete is recoverable removal with downstream invalidation if the "
        "deleted image was the planning reference. Restore does not approve "
        "clinical data. No registration or other clinical computation is run. "
        "Files must already be uploaded; model-supplied paths are not accepted."
    )
    input_schema = {'type':'object','additionalProperties':False,'required':['action'],
        'properties':{'action':{'type':'string','enum':['list','show','hide','set_reference','move','rename','appearance','delete','restore']},
            'image_id':{'type':'string','pattern':'^[0-9a-f]{32}$'},
            'name':{'type':'string','maxLength':160,'minLength':1},
            'role':{'type':'string','enum':['preop','intraop','unclassified']},
            'opacity':{'type':'number','minimum':0,'maximum':1},
            'color':{'type':'string','pattern':'^#[0-9a-fA-F]{6}$'},
            'window_width':{'type':'number','exclusiveMinimum':0},'window_level':{'type':'number'},
            'expected_collection_revision':{'type':'integer','minimum':0}}}

    def __init__(self, agent):
        self._agent = agent

    def is_available(self):
        config = self._agent.config
        return bool(getattr(self._agent,'_workspace_store',None) and config.get('_workspace_owner_id')
            and config.get('_workspace_session_id') and config.get('_workspace_timepoint_id'))

    def _execute(self, **kwargs):
        agent = self._agent
        language = resolve_timepoint_language(agent=agent)
        zh = language == 'zh'
        try:
            action = kwargs.get('action')
            fields = {'list':{'action'},'show':{'action','image_id'},'hide':{'action','image_id'},
                'set_reference':{'action','image_id'},'move':{'action','image_id','role'},
                'rename':{'action','image_id','name'},'appearance':{'action','image_id','opacity','color','window_width','window_level'},
                'delete':{'action','image_id'},'restore':{'action','image_id'}}
            if action not in fields or set(kwargs) - fields[action] - {'expected_collection_revision'}:
                raise TimepointError('Image operation arguments do not match their action')
            config = agent.config
            owner,sid,tid = (config.get(key) for key in ('_workspace_owner_id','_workspace_session_id','_workspace_timepoint_id'))
            facade = getattr(agent,'_workspace_store',None)
            store = getattr(facade,'raw',facade)
            if not store or not owner or not sid or not tid:
                raise TimepointError('An owned timepoint binding is required')
            from web.timepoint_images import TimepointImageService
            service = TimepointImageService(store)
            runtime = getattr(agent,'_workspace_scoped_chat_runtime',None)
            with store._case_guard(owner,sid):
                if runtime is not None:
                    runtime.assert_current()
                collection = service.list_images(owner,sid,tid)
                if action == 'list':
                    message = '已读取当前时间点的图像集合。' if zh else 'Read the current timepoint image collection.'
                    return ToolResult(True,data=collection,message=message,metadata={'collection':collection,'read_only':True})
                image = kwargs.get('image_id')
                candidates = collection['images'] + (collection['trashed_images'] if action == 'restore' else [])
                if not image or not any(row['id'] == image for row in candidates):
                    raise TimepointError('Select an actual image ID from this target collection')
                editor = (getattr(agent,'_active_turn_context',{}) or {}).get('editor_token') or ''
                observed = kwargs.get('expected_collection_revision',collection['collection_revision'])
                if action == 'delete':
                    result = service.delete_image(owner,sid,tid,image,expected_collection_revision=observed,editor_token=editor)
                else:
                    patch = {'show':{'display':True},'hide':{'display':False},'set_reference':{'planning_reference':True},
                        'restore':{'restore':True}}.get(action)
                    if patch is None:
                        names = {'move':('role',),'rename':('name',),'appearance':('opacity','color','window_width','window_level')}[action]
                        patch = {key:kwargs[key] for key in names if key in kwargs}
                    result = service.update_image(owner,sid,tid,image,patch,expected_collection_revision=observed,editor_token=editor)
                saved = store.load_timepoint_snapshot(owner,sid,tid)
                if runtime is not None and saved['timepoint_clinical_revision'] != runtime.context.target.clinical_revision:
                    runtime.replace_published_workspace(saved)
            command = {'target':'timepoint','command':'refresh_images','value':{'timepoint_id':tid}}
            message = ('图像操作已保存，等待当前工作区同步显示。' if zh else
                'The image operation was saved; the current workspace display is pending refresh.')
            return ToolResult(True,data=result,message=message,metadata={'collection':result,'image_id':image,
                'published_to_timepoint':True,'ui_action':command,'viewer_mounted':False,
                'clinical_computation_performed':False})
        except (WorkspaceError,TimepointError,ValueError,TypeError) as exc:
            packet,_ = timepoint_error(exc,language)
            return ToolResult(False,error=packet['error'],message=packet['message'],metadata=packet)
