import torch
import torch.nn as nn
import torch.nn.functional as F

from ..general import xywh2xyxy
from ..loss import smooth_BCE, FocalLoss
from ..torch_utils import is_parallel
from ..metrics import bbox_iou
from .general import masks_iou, crop

class MaskIOULoss(nn.Module):
    def __init__(self) -> None:
        super().__init__()

    def forward(self, pred_mask, gt_mask, mxyxy=None, return_iou=False):
        """
        Args:
            pred_mask (torch.Tensor): prediction of masks, (80/160, 80/160, n)
            gt_mask (torch.Tensor): ground truth of masks, (80/160, 80/160, n)
            mxyxy (torch.Tensor): ground truth of boxes, (n, 4)
        """
        _, _, n = pred_mask.shape  # same as gt_mask
        pred_mask = pred_mask.sigmoid()
        if mxyxy is not None:
            pred_mask = crop(pred_mask, mxyxy)
            gt_mask = crop(gt_mask, mxyxy)
        pred_mask = pred_mask.permute(2, 0, 1).view(n, -1)
        gt_mask = gt_mask.permute(2, 0, 1).view(n, -1)
        iou = masks_iou(pred_mask, gt_mask)
        return iou if return_iou else (1.0 - iou)

class ComputeLoss:
    # Compute losses
    def __init__(self, model, autobalance=False, overlap=False):
        self.sort_obj_iou = False
        self.overlap = overlap
        device = next(model.parameters()).device  # get model device
        h = model.hyp  # hyperparameters

        # Define criteria
        BCEcls = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([h["cls_pw"]], device=device))
        BCEobj = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([h["obj_pw"]], device=device))

        self.mask_loss = MaskIOULoss()

        # Class label smoothing https://arxiv.org/pdf/1902.04103.pdf eqn 3
        self.cp, self.cn = smooth_BCE(eps=h.get("label_smoothing", 0.0))  # positive, negative BCE targets

        # Focal loss
        g = h["fl_gamma"]  # focal loss gamma
        if g > 0:
            BCEcls, BCEobj = FocalLoss(BCEcls, g), FocalLoss(BCEobj, g)

        det = model.module.model[-1] if is_parallel(model) else model.model[-1]  # Detect() module
        self.balance = {3: [4.0, 1.0, 0.4]}.get(det.nl, [4.0, 1.0, 0.25, 0.06, 0.02])  # P3-P7
        self.ssi = list(det.stride).index(16) if autobalance else 0  # stride 16 index
        self.BCEcls, self.BCEobj, self.gr, self.hyp, self.autobalance = (BCEcls, BCEobj, 1.0, h, autobalance,)
        for k in "na", "nc", "nl", "anchors", "nm":
            if hasattr(det, k):
                setattr(self, k, getattr(det, k))

    def __call__(self, preds, targets, masks):  # predictions, targets, model
        p = preds[0]
        # [batch-size, mask_dim, mask_hegiht, mask_width]
        proto_out = preds[1]
        mask_h, mask_w = proto_out.shape[2:]
        proto_out = proto_out.permute(0, 2, 3, 1)

        device = targets.device
        lcls, lbox, lobj, lseg = (
            torch.zeros(1, device=device), torch.zeros(1, device=device), torch.zeros(1, device=device),
            torch.zeros(1, device=device),)
        tcls, tbox, indices, anchors, tidxs, xywh = self.build_targets(p, targets)  # targets
        # Losses
        for i, pi in enumerate(p):  # layer index, layer predictions
            b, a, gj, gi = indices[i]  # image, anchor, gridy, gridx
            tobj = torch.zeros_like(pi[..., 0], device=device)  # target obj

            n = b.shape[0]  # number of targets
            if n:
                ps = pi[b, a, gj, gi]  # prediction subset corresponding to targets

                # Regression
                pxy = ps[:, :2].sigmoid() * 2.0 - 0.5
                pwh = (ps[:, 2:4].sigmoid() * 2) ** 2 * anchors[i]
                pbox = torch.cat((pxy, pwh), 1)  # predicted box
                iou = bbox_iou(pbox, tbox[i], CIoU=True).squeeze()  # iou(prediction, target)
                lbox += (1.0 - iou).mean()  # iou loss

                # Objectness
                score_iou = iou.detach().clamp(0).type(tobj.dtype)
                if self.sort_obj_iou:
                    sort_id = torch.argsort(score_iou)
                    b, a, gj, gi, score_iou = (b[sort_id], a[sort_id], gj[sort_id], gi[sort_id], score_iou[sort_id],)
                tobj[b, a, gj, gi] = 1.0 * ((1.0 - self.gr) + self.gr * score_iou)  # iou ratio

                # Classification
                if self.nc > 1:  # cls loss (only if multiple classes)
                    t = torch.full_like(ps[:, self.nm:], self.cn, device=device)  # targets
                    t[range(n), tcls[i]] = self.cp
                    lcls += self.BCEcls(ps[:, self.nm:], t)  # BCE

                # Mask Regression
                # TODO:
                # [bs * num_objs, img_h, img_w] -> [bs * num_objs, mask_h, mask_w]
                downsampled_masks = F.interpolate(masks[None, :], (mask_h, mask_w), mode="bilinear",
                    align_corners=False).squeeze(0)

                mxywh = xywh[i]
                mws, mhs = mxywh[:, 2:].T
                mws, mhs = mws / pi.shape[3], mhs / pi.shape[2]
                mxywhs = (mxywh / torch.tensor(pi.shape, device=mxywh.device)[[3, 2, 3, 2]] * torch.tensor(
                    [mask_w, mask_h, mask_w, mask_h], device=mxywh.device))
                mxyxys = xywh2xyxy(mxywhs)

                batch_lseg = torch.zeros(1, device=device)
                for bi in b.unique():
                    index = b == bi
                    if self.overlap:
                        mask_index = tidxs[i][index]
                        # h, w, n
                        mask_gti = downsampled_masks[bi][:, :, None].repeat(1, 1, index.sum())
                        # h, w, n
                        mask_gti = torch.where(mask_gti == mask_index, 1.0, 0.0)
                    else:
                        mask_gti = downsampled_masks[tidxs[i]][index]
                        mask_gti = mask_gti.permute(1, 2, 0).contiguous()

                    mw, mh = mws[index], mhs[index]
                    mxyxy = mxyxys[index]
                    psi = ps[index][:, 5: self.nm]
                    proto = proto_out[bi]

                    one_lseg = self.single_mask_loss(mask_gti, psi, proto, mxyxy, mw, mh)
                    batch_lseg += one_lseg

                    # # update tobj
                    # iou = iou.detach().clamp(0).type(tobj.dtype)
                    # tobj[b[index], a[index], gj[index], gi[index]] += 0.5 * iou[0]

                lseg += batch_lseg / len(b.unique())

            obji = self.BCEobj(pi[..., 4], tobj)
            lobj += obji * self.balance[i]  # obj loss
            if self.autobalance:
                self.balance[i] = self.balance[i] * 0.9999 + 0.0001 / obji.detach().item()

        if self.autobalance:
            self.balance = [x / self.balance[self.ssi] for x in self.balance]
        lbox *= self.hyp["box"]
        lobj *= self.hyp["obj"]
        lcls *= self.hyp["cls"]
        lseg *= self.hyp["box"]
        bs = tobj.shape[0]  # batch size

        loss = lbox + lobj + lcls + lseg
        return loss * bs, torch.cat((lbox, lseg, lobj, lcls)).detach()

    def single_mask_loss(self, gt_mask, pred, proto, xyxy, w, h):
        """mask loss of one single pic."""
        # (80, 80, 32) @ (32, n) -> (80, 80, n)
        pred_mask = proto @ pred.tanh().T
        # lseg_iou = self.mask_loss(pred_mask, gt_mask, xyxy)
        # iou = self.mask_loss(pred_mask, gt_mask, xyxy, return_iou=True)
        lseg = F.binary_cross_entropy_with_logits(pred_mask, gt_mask, reduction="none")
        lseg = crop(lseg, xyxy)
        lseg = lseg.mean(dim=(0, 1)) / w / h
        return lseg.mean()#, iou# + lseg_iou.mean()

    def build_targets(self, p, targets):
        # Build targets for compute_loss(), input targets(image,class,x,y,w,h)
        na, nt = self.na, targets.shape[0]  # number of anchors, targets
        tcls, tbox, indices, anch, tidxs, xywh = [], [], [], [], [], []
        gain = torch.ones(8, device=targets.device)  # normalized to gridspace gain
        ai = (
            torch.arange(na, device=targets.device).float().view(na, 1).repeat(1, nt))  # same as .repeat_interleave(nt)
        if self.overlap:
            batch = p[0].shape[0]
            ti = []
            for i in range(batch):
                # find number of targets of each image
                num = (targets[:, 0] == i).sum()
                # (na, num)
                ti.append(
                    torch.arange(num, device=targets.device)
                    .float()
                    .view(1, num)
                    .repeat(na, 1) + 1)
            # (na, nt)
            ti = torch.cat(ti, 1)
        else:
            ti = (
                torch.arange(nt, device=targets.device).float().view(1, nt).repeat(na, 1))  # same as .repeat_interleave(nt)

        targets = torch.cat((targets.repeat(na, 1, 1), ai[:, :, None], ti[:, :, None]), 2)  # append anchor indices

        g = 0.5  # bias
        off = (torch.tensor([[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1],  # j,k,l,m
            # [1, 1], [1, -1], [-1, 1], [-1, -1],  # jk,jm,lk,lm
        ], device=targets.device, ).float() * g)  # offsets

        for i in range(self.nl):
            anchors, shape = self.anchors[i], p[i].shape
            gain[2:6] = torch.tensor(shape)[[3, 2, 3, 2]] # xyxy gain

            # Match targets to anchors
            t = targets * gain
            if nt:
                # Matches
                r = t[:, :, 4:6] / anchors[:, None]  # wh ratio
                j = torch.max(r, 1.0 / r).max(2)[0] < self.hyp["anchor_t"]  # compare
                # j = wh_iou(anchors, t[:, 4:6]) > model.hyp['iou_t']  # iou(3,n)=wh_iou(anchors(3,2), gwh(n,2))
                t = t[j]  # filter

                # Offsets
                gxy = t[:, 2:4]  # grid xy
                gxi = gain[[2, 3]] - gxy  # inverse
                j, k = ((gxy % 1.0 < g) & (gxy > 1.0)).T
                l, m = ((gxi % 1.0 < g) & (gxi > 1.0)).T
                j = torch.stack((torch.ones_like(j), j, k, l, m))
                t = t.repeat((5, 1, 1))[j]
                offsets = (torch.zeros_like(gxy)[None] + off[:, None])[j]
            else:
                t = targets[0]
                offsets = 0

            # Define
            b, c = t[:, :2].long().T  # image, class
            gxy = t[:, 2:4]  # grid xy
            gwh = t[:, 4:6]  # grid wh
            gij = (gxy - offsets).long()
            gi, gj = gij.T  # grid xy indices

            # Append
            a = t[:, 6].long()  # anchor indices
            tidx = t[:, 7].long()
            indices.append((b, a, gj.clamp_(0, shape[2] - 1), gi.clamp_(0, shape[3] - 1))) # image, anchor, grid
            tbox.append(torch.cat((gxy - gij, gwh), 1))  # box
            anch.append(anchors[a])  # anchors
            tcls.append(c)  # class
            tidxs.append(tidx)
            xywh.append(torch.cat((gxy, gwh), 1))

        return tcls, tbox, indices, anch, tidxs, xywh