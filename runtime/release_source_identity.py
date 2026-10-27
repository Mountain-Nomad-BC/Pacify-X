"""Closed release source identity union; standalone proof never pretends to be Git."""
from pathlib import Path
import re
import zipfile
from .release_identity import _recorded_git_identity, _version, capture_git_identity, verify_recorded_git_identity

SCHEMA="px.release-source-identity/1.0"
GIT_DEFERRED={"state":"deferred_by_owner","satisfied":False}
KERNEL_FIELDS=("campaign_id","repair_campaign_id","release_version","extension_version","source_product_digest",
    "source_harness_digest","source_manifest_sha256","source_file_count","release_policy_sha256","release_identity_sha256")
FIELDS={"schema_version","identity_kind","valid","owner_authority","git_acceptance","source_freeze",
    "authored_tree_sha256","source_archive_sha256",*KERNEL_FIELDS}


def current_campaign(root):
    from .plan_registry import _planning_object,_require_current_campaign
    from .project_revision_succession import current_revision_root
    revision=current_revision_root(Path(root))
    if revision is not None:
        policy=_planning_object(revision/"validation-policy.json")
        _require_current_campaign(policy)
        return True
    path=Path(root)/"policies/rev1xx-validation.json"
    from .archive_io import reject_path_links
    reject_path_links(path)
    if not path.exists(): return False
    policy=_planning_object(path);_require_current_campaign(policy)
    return True


def source_identity_record(record):
    """Validate typed record data only; authentication remains a native reader duty."""
    if type(record) is not dict: raise ValueError("source identity must be an actual object")
    if record.get("schema_version")!=SCHEMA:
        if "identity_kind" in record: raise ValueError("unknown tagged source identity")
        return _recorded_git_identity(record)
    if set(record)!=FIELDS or record["identity_kind"]!="standalone_current_campaign" or record["valid"] is not True:
        raise ValueError("exact current source identity fields required")
    if record["owner_authority"]!="OWNER-FRESH-VALIDATION-001" or record["git_acceptance"]!=GIT_DEFERRED:
        raise ValueError("current source identity cannot satisfy deferred Git acceptance")
    for key in ("source_product_digest","source_harness_digest","source_manifest_sha256","release_policy_sha256",
                "release_identity_sha256","authored_tree_sha256","source_archive_sha256"):
        if type(record[key]) is not str or re.fullmatch("[0-9a-f]{64}",record[key]) is None: raise ValueError("invalid source digest")
    if type(record["source_file_count"]) is not int or not 0<record["source_file_count"]<=2000000:
        raise ValueError("invalid source file denominator")
    _version(record["release_version"])
    if any(type(record[key]) is not str or not 1<=len(record[key])<=512 for key in ("campaign_id","repair_campaign_id","extension_version")):
        raise ValueError("invalid source campaign identity")
    ref=record["source_freeze"]
    from .archive_io import portable_member_name
    if type(ref) is not dict or set(ref)!={"path","sha256"} or not portable_member_name(ref["path"],allow_directory=False).startswith("registry/source-freeze/current-campaign/") or re.fullmatch("[0-9a-f]{64}",str(ref["sha256"])) is None:
        raise ValueError("invalid final source-freeze reference")
    return dict(record)


def capture_release_source_identity(root,*,version):
    """Observe current native kernel and final retained/live bytes; never write or invoke Git in fresh campaigns."""
    root=Path(root).resolve(strict=True)
    try:
        if not current_campaign(root): return capture_git_identity(root,version=version)
        from .release_campaign import release_campaign_status
        from .release_repository_context import verify_source_anchor
        status=release_campaign_status(root,verify_source=True)
        if not status["valid"] or status["state"] not in ("active","certified"):
            raise ValueError("current source requires its genuine applied release identity")
        kernel=status["identity"]
        if kernel["release_version"]!=_version(version): raise ValueError("current source release version differs")
        verified=verify_source_anchor(root,kernel.get("source_freeze"),require_live=True)
        receipt=verified["receipt"]
        return source_identity_record({"schema_version":SCHEMA,"identity_kind":"standalone_current_campaign","valid":True,
            "owner_authority":"OWNER-FRESH-VALIDATION-001","git_acceptance":dict(GIT_DEFERRED),
            **{key:kernel[key] for key in KERNEL_FIELDS},"source_freeze":verified["reference"],
            "authored_tree_sha256":receipt["tree_sha256"],"source_archive_sha256":receipt["archive"]["sha256"]})
    except (OSError,ValueError,TypeError,KeyError,zipfile.BadZipFile) as error:
        return {"valid":False,"errors":["release source identity: "+str(error)],"git_acceptance":dict(GIT_DEFERRED)}


def verify_release_source_identity(root,record):
    try:
        value=source_identity_record(record)
        if value.get("schema_version")!=SCHEMA: return verify_recorded_git_identity(root,value)
        observed=capture_release_source_identity(root,version=value["release_version"])
        if observed!=value: raise ValueError("recorded source identity differs from independently observed final current bytes")
        return {"valid":True,"errors":[],"git_acceptance":dict(GIT_DEFERRED)}
    except (OSError,ValueError,TypeError,KeyError,zipfile.BadZipFile) as error:
        return {"valid":False,"errors":[str(error)]}


def provenance_source(record,product_digest):
    value=source_identity_record(record)
    if value.get("schema_version")==SCHEMA:
        if value["source_product_digest"]!=product_digest: raise ValueError("source identity product differs")
        return {"uri":"urn:px:campaign:"+value["campaign_id"]+":source-freeze",
            "digest":{"sha256":value["authored_tree_sha256"],"sourceManifestSha256":value["source_manifest_sha256"],
                "sourceArchiveSha256":value["source_archive_sha256"],"productSha256":product_digest}},value["campaign_id"]
    return {"uri":value["repository"],"digest":{"gitCommit":value["commit_sha"],"gitTree":value["tree_sha"],"productSha256":product_digest}},value["tag"]


def release_configuration_relative(candidate_id,kind):
    """Closed derived-control locator; never part of its own authored source hash."""
    import hashlib
    if type(candidate_id) is not str or not candidate_id.strip() or len(candidate_id)>512 or any(ord(c)<32 for c in candidate_id):
        raise ValueError("candidate identity must be bounded nonempty text")
    if kind not in ("stage-owner","automation"):raise ValueError("unknown native release config kind")
    return Path(".agentic_engineering_os_px/runtime-core/release/configurations")/hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()/(kind+".json")
